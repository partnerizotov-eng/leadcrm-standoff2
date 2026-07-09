"""Withdrawals — a manager cashes out their OWN gold balance."""
import secrets

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from . import db
from .db import execute, get_setting, log_activity, query_all, query_one, set_setting
from .notifications import notify, notify_all_admins
from .security import admin_required, login_required
from .uploads import save_screenshot

bp = Blueprint("withdrawals", __name__)

MIN_WITHDRAWAL = 30
DEFAULT_COMMISSION_PCT = 20


def commission_pct():
    return float(get_setting("commission_pct", DEFAULT_COMMISSION_PCT))


def compute_list_price(amount, pct=None):
    if pct is None:
        pct = commission_pct()
    base = amount * (1 + pct / 100)
    unique_cents = secrets.randbelow(100) / 100
    return round(base + unique_cents, 2)


def has_pending_withdrawal(manager_id):
    """Блокирует новый вывод, пока предыдущий не пройдёт полный цикл:
    продажа -> подтверждение админом -> скрин выплаты от менеджера ->
    финальное подтверждение админом.
    """
    pending = query_one("""
        SELECT id FROM withdrawals
        WHERE manager_id = ?
        AND (
            status IN ('awaiting_listing', 'proof_submitted')
            OR (status = 'completed' AND payout_admin_confirmed = 0)
        )
        LIMIT 1
    """, (manager_id,))
    return pending is not None


@bp.route("/withdrawals")
@login_required
def index():
    role, manager_id = session["role"], session["manager_id"]
    where, params = [], []

    if role != "admin":
        where.append("w.manager_id=?")
        params.append(manager_id)

    status_filter = request.args.get("status", "")
    if status_filter:
        where.append("w.status=?")
        params.append(status_filter)

    sql = "SELECT w.*, m.name manager_name FROM withdrawals w JOIN managers m ON m.id=w.manager_id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY w.created_at DESC LIMIT 200"
    rows = query_all(sql, tuple(params))

    events_by_withdrawal = {}
    for w in rows:
        events = query_all("SELECT * FROM withdrawal_events WHERE withdrawal_id=? ORDER BY id", (w["id"],))
        events_by_withdrawal[w["id"]] = [dict(e) for e in events]

    my_balance = query_one("SELECT balance FROM managers WHERE id=?", (manager_id,))["balance"]
    pending_block = has_pending_withdrawal(manager_id) if role != "admin" else False

    # Раздел "Выплаты" — только полностью завершённые и подтверждённые админом выводы
    payout_where = ["payout_admin_confirmed = 1"]
    payout_params = []
    if role != "admin":
        payout_where.append("manager_id = ?")
        payout_params.append(manager_id)
    payouts_sql = ("SELECT w.*, m.name manager_name FROM withdrawals w JOIN managers m ON m.id=w.manager_id "
                   "WHERE " + " AND ".join(payout_where) + " ORDER BY w.updated_at DESC LIMIT 100")
    payouts = query_all(payouts_sql, tuple(payout_params))

    return render_template("withdrawals.html",
                          withdrawals=[dict(r) for r in rows],
                          events_by_withdrawal=events_by_withdrawal,
                          is_admin=(role == "admin"),
                          min_withdrawal=MIN_WITHDRAWAL,
                          status_filter=status_filter,
                          my_balance=my_balance,
                          pending_block=pending_block,
                          payouts=[dict(p) for p in payouts])


@bp.route("/withdrawals/request", methods=["POST"])
@login_required
def create():
    manager_id = session["manager_id"]
    manager = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))

    if has_pending_withdrawal(manager_id):
        flash("⛔ Дождитесь, пока текущий вывод пройдёт полную проверку администратором.", "error")
        return redirect(url_for("withdrawals.index"))

    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0

    if amount < MIN_WITHDRAWAL:
        flash(f"Минимальная сумма вывода — {MIN_WITHDRAWAL}G.", "error")
        return redirect(url_for("withdrawals.index"))
    if amount > manager["balance"]:
        flash("На балансе недостаточно средств.", "error")
        return redirect(url_for("withdrawals.index"))

    pct = commission_pct()
    list_price = compute_list_price(amount, pct)

    instruction = (f"Выставьте скин на продажу за {list_price:.2f}G. "
                  f"После продажи пришлите скриншот подтверждения.")

    try:
        with db.transaction() as conn:
            cur = conn.execute("UPDATE managers SET balance = balance - ? WHERE id=? AND balance >= ?",
                               (amount, manager_id, amount))
            if cur.rowcount == 0:
                raise ValueError("insufficient_balance")

            wid = conn.execute(
                "INSERT INTO withdrawals (manager_id, requested_amount, commission_pct, list_price, status) "
                "VALUES (?, ?, ?, ?, 'awaiting_listing')", (manager_id, amount, pct, list_price)).lastrowid

            conn.execute("INSERT INTO manager_ledger (manager_id, amount, reason, reference_id, actor_manager_id) "
                        "VALUES (?, ?, 'withdrawal', ?, ?)", (manager_id, -amount, wid, manager_id))

            conn.execute("INSERT INTO withdrawal_events (withdrawal_id, actor, message) VALUES (?, 'system', ?)",
                        (wid, instruction))
    except ValueError:
        flash("На балансе недостаточно средств.", "error")
        return redirect(url_for("withdrawals.index"))

    admins = query_all("SELECT id FROM managers WHERE role='admin'")
    for admin in admins:
        notify(admin["id"],
               f"💰 Заявка на вывод от {manager['name']} на сумму {amount:.2f}G",
               url_for("withdrawals.index"))

    log_activity(f"Менеджер {manager['name']} создал заявку на вывод #{wid}: {amount:.2f}G.", manager_id)
    flash("✅ Заявка на вывод создана. Ожидайте подтверждения администратора.", "success")
    return redirect(url_for("withdrawals.index"))


@bp.route("/withdrawals/<int:wid>/proof", methods=["POST"])
@login_required
def submit_proof(wid):
    """Менеджер прикрепляет скриншот продажи скина. Только один раз — до
    проверки администратором замена не предусмотрена."""
    manager_id, role = session["manager_id"], session["role"]
    w = query_one("SELECT * FROM withdrawals WHERE id=?", (wid,))
    if not w or (role != "admin" and w["manager_id"] != manager_id):
        flash("Заявка не найдена или не ваша.", "error")
        return redirect(url_for("withdrawals.index"))
    if w["status"] != "awaiting_listing":
        flash("На этом этапе скриншот уже не требуется.", "error")
        return redirect(url_for("withdrawals.index"))

    filename = save_screenshot(request.files.get("screenshot"), "wd")
    if not filename:
        flash("Прикрепите скриншот продажи.", "error")
        return redirect(url_for("withdrawals.index"))

    execute("UPDATE withdrawals SET status='proof_submitted', updated_at=datetime('now') WHERE id=?", (wid,))
    execute("INSERT INTO withdrawal_events (withdrawal_id, actor, actor_id, message, screenshot) "
            "VALUES (?, 'manager', ?, 'Скриншот продажи прикреплён.', ?)", (wid, manager_id, filename))

    admins = query_all("SELECT id FROM managers WHERE role='admin'")
    for admin in admins:
        notify(admin["id"],
               f"📸 Вывод #{wid}: менеджер прислал скриншот продажи, нужна проверка.",
               url_for("withdrawals.index"))

    flash("✅ Скриншот отправлен администратору.", "success")
    return redirect(url_for("withdrawals.index"))


@bp.route("/withdrawals/<int:wid>/complete", methods=["POST"])
@admin_required
def complete(wid):
    w = query_one("SELECT * FROM withdrawals WHERE id=?", (wid,))
    if not w:
        flash("Заявка не найдена.", "error")
        return redirect(url_for("withdrawals.index"))
    if w["status"] != "proof_submitted" and w["status"] != "awaiting_listing":
        flash("Сначала нужен скриншот продажи от менеджера.", "error")
        return redirect(url_for("withdrawals.index"))

    admin_id = session["manager_id"]
    comment = request.form.get("comment", "").strip()

    execute("UPDATE withdrawals SET status='completed', updated_at=datetime('now') WHERE id=?", (wid,))
    execute("INSERT INTO withdrawal_events (withdrawal_id, actor, actor_id, message, screenshot) "
            "VALUES (?, 'admin', ?, ?, ?)",
            (wid, admin_id, comment or "Вывод подтверждён, деньги отправлены менеджеру.", None))

    notify(w["manager_id"],
           f"✅ Вывод #{wid} подтверждён администратором. Пришлите скриншот о получении выплаты.",
           url_for("withdrawals.index"))
    log_activity(f"Вывод #{wid} подтверждён администратором.", admin_id)
    flash("✅ Вывод подтверждён. Ожидаем от менеджера скриншот получения выплаты.", "success")
    return redirect(url_for("withdrawals.index"))


@bp.route("/withdrawals/<int:wid>/confirm-payout", methods=["POST"])
@login_required
def confirm_payout(wid):
    """Менеджер ОДИН РАЗ прикрепляет скриншот о получении выплаты.
    Это отправляет заявку на финальную проверку администратору —
    замена до проверки не предусмотрена."""
    manager_id, role = session["manager_id"], session["role"]
    w = query_one("SELECT * FROM withdrawals WHERE id=?", (wid,))

    if not w or (role != "admin" and w["manager_id"] != manager_id):
        flash("Заявка не найдена или не ваша.", "error")
        return redirect(url_for("withdrawals.index"))

    if w["status"] != "completed":
        flash("Подтвердить получение выплаты можно только после одобрения администратором.", "error")
        return redirect(url_for("withdrawals.index"))

    if w["payout_confirmed"]:
        flash("Скриншот уже отправлен и ожидает проверки администратором.", "error")
        return redirect(url_for("withdrawals.index"))

    filename = save_screenshot(request.files.get("screenshot"), "payout")
    if not filename:
        flash("Прикрепите скриншот о получении выплаты.", "error")
        return redirect(url_for("withdrawals.index"))

    execute("UPDATE withdrawals SET payout_confirmed=1, payout_screenshot=?, updated_at=datetime('now') WHERE id=?",
            (filename, wid))
    execute("INSERT INTO withdrawal_events (withdrawal_id, actor, actor_id, message, screenshot) "
            "VALUES (?, 'manager', ?, '📥 Менеджер прислал скриншот получения выплаты — ожидается проверка администратором.', ?)",
            (wid, manager_id, filename))

    admins = query_all("SELECT id FROM managers WHERE role='admin'")
    for admin in admins:
        notify(admin["id"],
               f"📥 Вывод #{wid}: менеджер прислал подтверждение выплаты, нужна финальная проверка.",
               url_for("withdrawals.index"))

    log_activity(f"Вывод #{wid}: менеджер отправил скриншот получения выплаты на проверку.", manager_id)
    flash("✅ Скриншот отправлен администратору на проверку.", "success")
    return redirect(url_for("withdrawals.index"))


@bp.route("/withdrawals/<int:wid>/admin-confirm-payout", methods=["POST"])
@admin_required
def admin_confirm_payout(wid):
    """Администратор финально подтверждает получение выплаты менеджером,
    прикрепляя собственный скриншот как официальное доказательство.
    Только после этого разблокируется новый вывод и запись попадает
    в раздел «Выплаты»."""
    w = query_one("SELECT * FROM withdrawals WHERE id=?", (wid,))
    if not w:
        flash("Заявка не найдена.", "error")
        return redirect(url_for("withdrawals.index"))

    if w["status"] != "completed" or not w["payout_confirmed"]:
        flash("Сначала менеджер должен прислать скриншот получения выплаты.", "error")
        return redirect(url_for("withdrawals.index"))

    if w["payout_admin_confirmed"]:
        flash("Уже подтверждено ранее.", "error")
        return redirect(url_for("withdrawals.index"))

    admin_id = session["manager_id"]
    comment = request.form.get("comment", "").strip()

    filename = save_screenshot(request.files.get("admin_screenshot"), "payoutproof")
    if not filename:
        flash("Прикрепите собственный скриншот-доказательство выплаты.", "error")
        return redirect(url_for("withdrawals.index"))

    execute("""UPDATE withdrawals
               SET payout_admin_confirmed=1, payout_admin_screenshot=?, payout_admin_comment=?, updated_at=datetime('now')
               WHERE id=?""", (filename, comment, wid))
    execute("INSERT INTO withdrawal_events (withdrawal_id, actor, actor_id, message, screenshot) "
            "VALUES (?, 'admin', ?, ?, ?)",
            (wid, admin_id, comment or "✅ Администратор подтвердил получение выплаты менеджером.", filename))

    from .referrals import on_withdrawal_completed
    on_withdrawal_completed(w["manager_id"])

    from .achievements import trigger_achievement_check
    trigger_achievement_check(w["manager_id"])

    notify(w["manager_id"],
           f"✅ Вывод #{wid} полностью завершён. Теперь можно запросить новый вывод.",
           url_for("withdrawals.index"))
    log_activity(f"Вывод #{wid}: финально подтверждён администратором.", admin_id)
    flash("✅ Подтверждено. Запись добавлена в раздел «Выплаты».", "success")
    return redirect(url_for("withdrawals.index"))


@bp.route("/withdrawals/<int:wid>/admin-reject-payout", methods=["POST"])
@admin_required
def admin_reject_payout(wid):
    """Администратор отклоняет присланный менеджером скрин подтверждения
    выплаты — сбрасывает его, менеджер должен прислать заново."""
    w = query_one("SELECT * FROM withdrawals WHERE id=?", (wid,))
    if not w or not w["payout_confirmed"]:
        flash("Нечего отклонять.", "error")
        return redirect(url_for("withdrawals.index"))

    admin_id = session["manager_id"]
    comment = request.form.get("comment", "").strip()

    execute("UPDATE withdrawals SET payout_confirmed=0, payout_screenshot=NULL, updated_at=datetime('now') WHERE id=?", (wid,))
    execute("INSERT INTO withdrawal_events (withdrawal_id, actor, actor_id, message) "
            "VALUES (?, 'admin', ?, ?)",
            (wid, admin_id, comment or "❌ Скриншот подтверждения выплаты отклонён, пришлите новый."))

    notify(w["manager_id"],
           f"❌ Вывод #{wid}: скриншот подтверждения выплаты отклонён. Пришлите новый.",
           url_for("withdrawals.index"))
    log_activity(f"Вывод #{wid}: подтверждение выплаты отклонено администратором.", admin_id)
    flash("❌ Отклонено, менеджер должен прислать скриншот заново.", "success")
    return redirect(url_for("withdrawals.index"))


@bp.route("/withdrawals/<int:wid>/reject", methods=["POST"])
@admin_required
def reject(wid):
    w = query_one("SELECT * FROM withdrawals WHERE id=?", (wid,))
    if not w:
        flash("Заявка не найдена.", "error")
        return redirect(url_for("withdrawals.index"))
    if w["status"] == "completed":
        flash("Завершённый вывод нельзя отклонить.", "error")
        return redirect(url_for("withdrawals.index"))

    admin_id = session["manager_id"]
    comment = request.form.get("comment", "").strip()

    with db.transaction() as conn:
        conn.execute("UPDATE withdrawals SET status='rejected', updated_at=datetime('now') WHERE id=?", (wid,))
        conn.execute("UPDATE managers SET balance = balance + ? WHERE id=?",
                    (w["requested_amount"], w["manager_id"]))
        conn.execute("INSERT INTO manager_ledger (manager_id, amount, reason, reference_id, actor_manager_id) "
                    "VALUES (?, ?, 'withdrawal_refund', ?, ?)",
                    (w["manager_id"], w["requested_amount"], wid, admin_id))
        conn.execute("INSERT INTO withdrawal_events (withdrawal_id, actor, actor_id, message) "
                    "VALUES (?, 'admin', ?, ?)",
                    (wid, admin_id, comment or "Вывод отклонён, баланс возвращён."))

    notify(w["manager_id"], f"❌ Вывод #{wid} отклонён, ваш баланс восстановлен.", url_for("withdrawals.index"))
    log_activity(f"Вывод #{wid} отклонён администратором." + (f' Причина: {comment}' if comment else ''), admin_id)
    flash("❌ Вывод отклонён, баланс возвращён.", "success")
    return redirect(url_for("withdrawals.index"))


@bp.route("/settings/commission", methods=["POST"])
@admin_required
def set_commission():
    try:
        pct = float(request.form.get("commission_pct", DEFAULT_COMMISSION_PCT))
    except ValueError:
        pct = DEFAULT_COMMISSION_PCT
    pct = max(0, min(90, pct))
    set_setting("commission_pct", pct)
    log_activity(f"Администратор изменил комиссию площадки на {pct}%.", session.get("manager_id"))
    flash(f"Комиссия установлена: {pct}%.", "success")
    return redirect(url_for("withdrawals.index"))


def attach_payment_proof(withdrawal_id, proof_id):
    """(Legacy, для админ-панели) Прикрепить доказательство выплаты к выводу."""
    withdrawal = query_one("SELECT * FROM withdrawals WHERE id = ?", (withdrawal_id,))
    if not withdrawal:
        return False, "❌ Вывод не найден"
    execute("UPDATE withdrawals SET payment_proof_id = ? WHERE id = ?", (proof_id, withdrawal_id))
    return True, "✅ Доказательство выплаты прикреплено"


def get_withdrawal_with_proof(withdrawal_id):
    sql = """
        SELECT w.*, pp.file_path as proof_file_path, pp.description as proof_description
        FROM withdrawals w
        LEFT JOIN payment_proofs pp ON w.payment_proof_id = pp.id
        WHERE w.id = ?
    """
    return query_one(sql, (withdrawal_id,))
