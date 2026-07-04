"""Withdrawals — a manager cashes out their OWN gold balance."""
import random
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
    """Цена, которую нужно выставить за скин, чтобы после комиссии площадки
    менеджер получил примерно ``amount`` голды.

    К базовой цене добавляются случайные копейки, поэтому у каждой заявки
    получается уникальная сумма — так оператору проще сопоставить лот на
    площадке с конкретной заявкой на вывод. Если ``pct`` не передан — берётся
    текущая комиссия из настроек.
    """
    if pct is None:
        pct = commission_pct()
    base = amount * (1 + pct / 100)
    unique_cents = secrets.randbelow(100) / 100  # 0.00 .. 0.99
    return round(base + unique_cents, 2)


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

    return render_template("withdrawals.html", 
                          withdrawals=[dict(r) for r in rows],
                          events_by_withdrawal=events_by_withdrawal, 
                          is_admin=(role == "admin"),
                          min_withdrawal=MIN_WITHDRAWAL, 
                          status_filter=status_filter, 
                          my_balance=my_balance)


@bp.route("/withdrawals/request", methods=["POST"])
@login_required
def create():
    manager_id = session["manager_id"]
    manager = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))

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

    # Уведомление админам
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
    
    # Уведомление админам
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
            (wid, admin_id, comment or "Вывод подтверждён, покупка выполнена.", None))
    
    notify(w["manager_id"], f"✅ Вывод #{wid} завершён администратором.", url_for("withdrawals.index"))
    log_activity(f"Вывод #{wid} подтверждён администратором.", admin_id)
    flash("✅ Вывод отмечен как завершённый.", "success")
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