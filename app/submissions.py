"""Submissions — a manager's claim that a lead posted their game ID this
round, with a screenshot as proof."""
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from . import db
from .db import execute, log_activity, query_all, query_one
from .notifications import notify, notify_all_admins
from .security import admin_required, login_required
from .uploads import save_screenshot

bp = Blueprint("submissions", __name__)

ROUND_SLOTS = ["12:00", "18:00", "00:00"]
APPROVAL_REWARD = 10
PENALTY_AMOUNT = 1


@bp.route("/submissions")
@login_required
def index():
    role, manager_id = session["role"], session["manager_id"]
    status_filter = request.args.get("status", "")

    where, params = [], []
    if role != "admin":
        where.append("s.manager_id=?")
        params.append(manager_id)
    if status_filter:
        where.append("s.status=?")
        params.append(status_filter)

    sql = ("SELECT s.*, l.name lead_name, l.vk_url, l.vk_id, m.name manager_name, "
           "m.balance as manager_balance "
           "FROM submissions s JOIN leads l ON l.id=s.lead_id JOIN managers m ON m.id=s.manager_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.created_at DESC LIMIT 200"

    rows = query_all(sql, tuple(params))
    
    # Для менеджера показываем только его заявки, для админа - все
    return render_template("submissions.html", 
                          submissions=[dict(r) for r in rows],
                          round_slots=ROUND_SLOTS, 
                          status_filter=status_filter,
                          is_admin=(role == "admin"), 
                          penalty_amount=PENALTY_AMOUNT)


@bp.route("/leads/<int:lead_id>/submit", methods=["POST"])
@login_required
def create(lead_id):
    manager_id, role = session["manager_id"], session["role"]
    lead = query_one("SELECT * FROM leads WHERE id=?", (lead_id,))
    
    # Проверка: либо админ, либо менеджер владелец лида
    if not lead or (role != "admin" and lead["assigned_manager_id"] != manager_id):
        flash("Лид не найден или не ваш.", "error")
        return redirect(url_for("leads.index"))

    round_slot = request.form.get("round_slot", "")
    if round_slot not in ROUND_SLOTS:
        flash("Выберите раунд розыгрыша.", "error")
        return redirect(url_for("leads.index"))
    round_date = request.form.get("round_date") or date.today().isoformat()

    # Проверка на дубликат
    existing = query_one("SELECT * FROM submissions WHERE lead_id=? AND round_date=? AND round_slot=?",
                         (lead_id, round_date, round_slot))
    if existing and existing["status"] != "rejected":
        flash("На этот раунд уже отправлена заявка по этому лиду.", "error")
        return redirect(url_for("leads.index"))

    # Сохранение скриншота
    filename = save_screenshot(request.files.get("screenshot"), "sub")
    if not filename:
        flash("Прикрепите скриншот (PNG/JPG, до 8 МБ).", "error")
        return redirect(url_for("leads.index"))

    # Создание или обновление заявки
    if existing:
        sub_id = existing["id"]
        execute("UPDATE submissions SET manager_id=?, screenshot=?, status='pending', "
                "admin_comment='', reviewed_by=NULL, reviewed_at=NULL, created_at=datetime('now') "
                "WHERE id=?", (manager_id, filename, sub_id))
    else:
        sub_id = execute(
            "INSERT INTO submissions (lead_id, manager_id, round_date, round_slot, screenshot) "
            "VALUES (?, ?, ?, ?, ?)", (lead_id, manager_id, round_date, round_slot, filename))
    
    # Уведомление админам
    admins = query_all("SELECT id FROM managers WHERE role='admin'")
    for admin in admins:
        notify(admin["id"], 
               f"📸 Новая заявка на проверку от {session.get('name')} для {lead['name'] or lead['vk_id']}",
               url_for("submissions.index"))
    
    flash("✅ Заявка отправлена на проверку администратору.", "success")
    return redirect(url_for("leads.index"))


@bp.route("/submissions/<int:sub_id>/review", methods=["POST"])
@admin_required
def review(sub_id):
    sub = query_one("SELECT * FROM submissions WHERE id=?", (sub_id,))
    if not sub:
        flash("Заявка не найдена.", "error")
        return redirect(url_for("submissions.index"))
    if sub["status"] != "pending":
        flash("Эта заявка уже рассмотрена.", "error")
        return redirect(url_for("submissions.index"))

    decision = request.form.get("decision")
    if decision not in ("approved", "rejected"):
        flash("Некорректное решение.", "error")
        return redirect(url_for("submissions.index"))
    comment = request.form.get("comment", "").strip()
    admin_id = session["manager_id"]

    if decision == "approved":
        with db.transaction() as conn:
            conn.execute(
                "UPDATE submissions SET status=?, admin_comment=?, reviewed_by=?, reviewed_at=datetime('now') "
                "WHERE id=?", (decision, comment, admin_id, sub_id))

            # Начисление лиду
            conn.execute("INSERT INTO balance_ledger (lead_id, amount, reason, reference_id, actor_manager_id) "
                        "VALUES (?, ?, 'submission_approved', ?, ?)",
                        (sub["lead_id"], APPROVAL_REWARD, sub_id, admin_id))
            conn.execute("UPDATE leads SET balance = balance + ? WHERE id=?",
                        (APPROVAL_REWARD, sub["lead_id"]))
            
            # Начисление менеджеру
            conn.execute("INSERT INTO manager_ledger (manager_id, amount, reason, reference_id, actor_manager_id) "
                        "VALUES (?, ?, 'submission_approved', ?, ?)",
                        (sub["manager_id"], APPROVAL_REWARD, sub_id, admin_id))
            conn.execute("UPDATE managers SET balance = balance + ?, total_earned = total_earned + ? WHERE id=?",
                        (APPROVAL_REWARD, APPROVAL_REWARD, sub["manager_id"]))
            
            # Обновление статуса лида
            new_count_row = conn.execute("SELECT COUNT(*) c FROM submissions WHERE lead_id=? AND status='approved'",
                                         (sub["lead_id"],)).fetchone()
            new_count = new_count_row["c"]
            new_status = "returning" if new_count >= 2 else "participated"
            conn.execute("UPDATE leads SET participation_count=?, status=?, last_status_change=datetime('now') "
                        "WHERE id=?", (new_count, new_status, sub["lead_id"]))

        # Реферальная система: засчитываем заявку рефереру и, если он уже
        # активный реферал, начисляем 20% override с этого начисления.
        from .referrals import on_submission_approved, apply_referral_override
        on_submission_approved(sub["manager_id"])
        apply_referral_override(sub["manager_id"], APPROVAL_REWARD, "заявка одобрена")

        msg = f"✅ Заявка одобрена! Начислено {APPROVAL_REWARD}G на ваш баланс."
        if comment:
            msg += f" Комментарий: {comment}"
        notify(sub["manager_id"], msg, url_for("submissions.index"))
        log_activity(f"Заявка #{sub_id} одобрена администратором. Комментарий: {comment}", admin_id)
        flash("✅ Заявка одобрена, начисления выполнены.", "success")
        
    else:  # rejected with penalty
        with db.transaction() as conn:
            conn.execute(
                "UPDATE submissions SET status=?, admin_comment=?, reviewed_by=?, reviewed_at=datetime('now') "
                "WHERE id=?", (decision, comment, admin_id, sub_id))
            
            # Штраф менеджеру за ошибку
            manager_balance = conn.execute("SELECT balance FROM managers WHERE id=?", (sub["manager_id"],)).fetchone()
            if manager_balance and manager_balance["balance"] >= PENALTY_AMOUNT:
                conn.execute("UPDATE managers SET balance = balance - ? WHERE id=?",
                            (PENALTY_AMOUNT, sub["manager_id"]))
                conn.execute("INSERT INTO manager_ledger (manager_id, amount, reason, reference_id, actor_manager_id, note) "
                            "VALUES (?, ?, 'submission_penalty', ?, ?, ?)",
                            (sub["manager_id"], -PENALTY_AMOUNT, sub_id, admin_id, 
                             f"Штраф за ошибку: {comment or 'без комментария'}"))

        msg = f"❌ Заявка отклонена. С вашего баланса списано {PENALTY_AMOUNT}G за ошибку."
        if comment:
            msg += f" Комментарий администратора: {comment}"
        notify(sub["manager_id"], msg, url_for("submissions.index"))
        log_activity(f"Заявка #{sub_id} отклонена администратором. Комментарий: {comment}", admin_id)
        flash(f"❌ Заявка отклонена, списано {PENALTY_AMOUNT}G с менеджера.", "error")

    return redirect(url_for("submissions.index"))