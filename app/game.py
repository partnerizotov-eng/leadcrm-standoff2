"""Маршруты для интеграции со Standoff 2 и поддержки"""
from flask import Blueprint, jsonify, render_template, request, session, flash, redirect, url_for, current_app
from .security import login_required, admin_required
from .db import query_one, query_all, execute
from .standoff2 import Standoff2Manager
from .models import GameAccount, GoldWithdrawal, ManagerStats
from .notifications import notify

bp = Blueprint("game", __name__, url_prefix="/game")
MIN_WITHDRAWAL = 10

def get_standoff2():
    return Standoff2Manager()

# ==================== ВЫВОД В ИГРУ ====================

@bp.route("/verify/<int:lead_id>", methods=["POST"])
@login_required
def verify_player(lead_id):
    manager_id = session["manager_id"]
    game_id = request.form.get("game_id", "").strip()
    
    if not game_id:
        flash("Введите игровой ID", "error")
        return redirect(url_for("leads.index"))
    
    lead = query_one(
        "SELECT * FROM leads WHERE id = ? AND assigned_manager_id = ?",
        (lead_id, manager_id)
    )
    if not lead and session.get("role") != "admin":
        flash("Лид не найден или не ваш", "error")
        return redirect(url_for("leads.index"))
    
    standoff2 = get_standoff2()
    success, message = standoff2.link_game_account(lead_id, game_id, manager_id)
    
    if success:
        flash(message, "success")
    else:
        flash(message, "error")
    
    return redirect(url_for("leads.index"))

@bp.route("/withdraw/<int:lead_id>", methods=["POST"])
@login_required
def withdraw_gold(lead_id):
    manager_id = session["manager_id"]
    
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        flash("Некорректная сумма", "error")
        return redirect(url_for("leads.index"))
    
    if amount < MIN_WITHDRAWAL:
        flash(f"Минимальная сумма вывода - {MIN_WITHDRAWAL}G", "error")
        return redirect(url_for("leads.index"))
    
    lead = query_one(
        "SELECT * FROM leads WHERE id = ? AND assigned_manager_id = ?",
        (lead_id, manager_id)
    )
    if not lead and session.get("role") != "admin":
        flash("Лид не найден или не ваш", "error")
        return redirect(url_for("leads.index"))
    
    if lead["balance"] < amount:
        flash(f"Недостаточно голды. Доступно: {lead['balance']:.2f}G", "error")
        return redirect(url_for("leads.index"))
    
    if not lead["game_id"]:
        flash("Игровой аккаунт не привязан. Сначала привяжите.", "error")
        return redirect(url_for("leads.index"))
    
    standoff2 = get_standoff2()
    success, message = standoff2.withdraw_gold_to_game(lead_id, amount, manager_id)
    
    if success:
        flash(message, "success")
    else:
        flash(message, "error")
    
    return redirect(url_for("leads.index"))

@bp.route("/withdrawals")
@login_required
def withdrawals_list():
    manager_id = session["manager_id"]
    role = session.get("role")
    
    if role == "admin":
        withdrawals = query_all("""
            SELECT w.*, l.name as lead_name, m.name as manager_name
            FROM game_withdrawals w
            JOIN leads l ON l.id = w.lead_id
            JOIN managers m ON m.id = w.manager_id
            ORDER BY w.created_at DESC
            LIMIT 100
        """)
    else:
        withdrawals = query_all("""
            SELECT w.*, l.name as lead_name
            FROM game_withdrawals w
            JOIN leads l ON l.id = w.lead_id
            WHERE w.manager_id = ?
            ORDER BY w.created_at DESC
            LIMIT 50
        """, (manager_id,))
    
    return render_template("game_withdrawals.html", 
                          withdrawals=[dict(w) for w in withdrawals],
                          is_admin=(role == "admin"),
                          min_withdrawal=MIN_WITHDRAWAL)

@bp.route("/leaderboard")
@login_required
def leaderboard():
    players = query_all("""
        SELECT l.id, l.name, l.game_id, l.balance, l.game_rank,
               COUNT(p.id) as participations,
               (SELECT COUNT(*) FROM game_withdrawals WHERE lead_id = l.id) as withdrawals_count
        FROM leads l
        LEFT JOIN participations p ON p.lead_id = l.id
        WHERE l.game_verified = 1
        GROUP BY l.id
        ORDER BY l.balance DESC
        LIMIT 20
    """)
    return render_template("game_leaderboard.html", players=[dict(p) for p in players])

@bp.route("/stats")
@login_required
def manager_game_stats():
    manager_id = session["manager_id"]
    stats = ManagerStats(manager_id).get_dashboard()
    rank = ManagerStats(manager_id).get_rank()
    goals = ManagerStats(manager_id).get_daily_goals()
    
    return render_template("game_stats.html", 
                          stats=stats, 
                          rank=rank,
                          goals=goals,
                          min_withdrawal=MIN_WITHDRAWAL)

# ==================== ПОДДЕРЖКА ====================

@bp.route("/support", methods=["GET", "POST"])
@login_required
def support():
    """Страница поддержки"""
    manager_id = session["manager_id"]
    role = session.get("role")
    manager = query_one("SELECT name FROM managers WHERE id = ?", (manager_id,))
    
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        ticket_id = request.form.get("ticket_id")
        is_from_admin = role == "admin"
        
        if not message:
            flash("Введите сообщение", "error")
            return redirect(url_for("game.support"))
        
        if is_from_admin and ticket_id:
            # Ответ админа на тикет
            ticket = query_one("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
            if ticket:
                execute("""
                    INSERT INTO support_messages (ticket_id, manager_id, admin_id, message, is_from_admin, is_read)
                    VALUES (?, ?, ?, ?, 1, 1)
                """, (ticket_id, ticket["manager_id"], manager_id, message))
                
                execute("""
                    UPDATE support_tickets 
                    SET status = 'waiting', updated_at = datetime('now')
                    WHERE id = ?
                """, (ticket_id,))
                
                notify(ticket["manager_id"], 
                       f"💬 Администратор ответил на ваш запрос",
                       "/game/support")
                
                flash("✅ Ответ отправлен менеджеру!", "success")
                return redirect(url_for("game.support_tickets"))
        else:
            # Новое сообщение от менеджера
            if not subject:
                flash("Укажите тему обращения", "error")
                return redirect(url_for("game.support"))
            
            if not ticket_id:
                # Создаем новый тикет
                ticket_id = execute("""
                    INSERT INTO support_tickets (manager_id, subject, status)
                    VALUES (?, ?, 'open')
                """, (manager_id, subject))
            
            # Сохраняем сообщение
            execute("""
                INSERT INTO support_messages (ticket_id, manager_id, message, is_from_admin, is_read)
                VALUES (?, ?, ?, 0, 0)
            """, (ticket_id, manager_id, message))
            
            # Уведомление админам
            admins = query_all("SELECT id FROM managers WHERE role='admin'")
            for admin in admins:
                notify(admin["id"], 
                       f"💬 Новое сообщение в поддержку от {manager['name']}: {subject[:50]}...",
                       "/game/support-tickets")
            
            flash("✅ Сообщение отправлено администратору!", "success")
            return redirect(url_for("game.support"))
    
    # GET - показ страницы
    if role == "admin":
        tickets = query_all("""
            SELECT t.*, m.name as manager_name,
                   (SELECT COUNT(*) FROM support_messages WHERE ticket_id = t.id AND is_from_admin = 0 AND is_read = 0) as unread_count,
                   (SELECT COUNT(*) FROM support_messages WHERE ticket_id = t.id) as total_messages
            FROM support_tickets t
            JOIN managers m ON m.id = t.manager_id
            WHERE t.status != 'closed'
            ORDER BY t.created_at DESC
        """)
        return render_template("support_admin.html", tickets=[dict(t) for t in tickets])
    else:
        tickets = query_all("""
            SELECT * FROM support_tickets 
            WHERE manager_id = ? AND status != 'closed'
            ORDER BY created_at DESC
        """, (manager_id,))
        
        messages = []
        if tickets:
            ticket_id = tickets[0]["id"]
            messages = query_all("""
                SELECT sm.*, 
                       COALESCE(m.name, 'Администратор') as sender_name,
                       sm.is_from_admin as is_admin
                FROM support_messages sm
                LEFT JOIN managers m ON m.id = sm.manager_id
                WHERE sm.ticket_id = ?
                ORDER BY sm.created_at ASC
            """, (ticket_id,))
            
            # Помечаем сообщения как прочитанные
            execute("""
                UPDATE support_messages 
                SET is_read = 1 
                WHERE ticket_id = ? AND is_from_admin = 1 AND is_read = 0
            """, (ticket_id,))
        
        return render_template("support.html", 
                              tickets=[dict(t) for t in tickets],
                              messages=[dict(m) for m in messages],
                              manager_name=manager["name"] if manager else "Менеджер")

@bp.route("/support/tickets")
@admin_required
def support_tickets():
    """Список всех тикетов для админа"""
    tickets = query_all("""
        SELECT t.*, m.name as manager_name,
               (SELECT COUNT(*) FROM support_messages WHERE ticket_id = t.id AND is_from_admin = 0 AND is_read = 0) as unread_count,
               (SELECT COUNT(*) FROM support_messages WHERE ticket_id = t.id) as total_messages
        FROM support_tickets t
        JOIN managers m ON m.id = t.manager_id
        ORDER BY 
            CASE t.status 
                WHEN 'open' THEN 1 
                WHEN 'waiting' THEN 2 
                ELSE 3 
            END,
            t.created_at DESC
    """)
    return render_template("support_admin.html", tickets=[dict(t) for t in tickets])

@bp.route("/support/ticket/<int:ticket_id>")
@login_required
def support_ticket(ticket_id):
    """Просмотр конкретного тикета"""
    role = session.get("role")
    manager_id = session["manager_id"]
    
    ticket = query_one("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
    if not ticket:
        flash("Тикет не найден", "error")
        return redirect(url_for("game.support"))
    
    if role != "admin" and ticket["manager_id"] != manager_id:
        flash("Доступ запрещен", "error")
        return redirect(url_for("game.support"))
    
    messages = query_all("""
        SELECT sm.*, 
               COALESCE(m.name, 'Администратор') as sender_name,
               sm.is_from_admin as is_admin
        FROM support_messages sm
        LEFT JOIN managers m ON m.id = sm.manager_id
        WHERE sm.ticket_id = ?
        ORDER BY sm.created_at ASC
    """, (ticket_id,))
    
    if role == "admin":
        execute("""
            UPDATE support_messages 
            SET is_read = 1 
            WHERE ticket_id = ? AND is_from_admin = 0 AND is_read = 0
        """, (ticket_id,))
    
    ticket_info = dict(ticket)
    if role == "admin":
        manager = query_one("SELECT name FROM managers WHERE id = ?", (ticket["manager_id"],))
        ticket_info["manager_name"] = manager["name"] if manager else "Неизвестно"
    
    return render_template("support_ticket.html", 
                          ticket=ticket_info,
                          messages=[dict(m) for m in messages],
                          is_admin=(role == "admin"))

@bp.route("/support/close/<int:ticket_id>", methods=["POST"])
@admin_required
def support_close(ticket_id):
    """Закрытие тикета"""
    execute("""
        UPDATE support_tickets 
        SET status = 'closed', closed_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
    """, (ticket_id,))
    
    ticket = query_one("SELECT manager_id FROM support_tickets WHERE id = ?", (ticket_id,))
    if ticket:
        notify(ticket["manager_id"], 
               "✅ Ваш тикет закрыт администратором. Спасибо за обращение!",
               "/game/support")
    
    flash("✅ Тикет закрыт", "success")
    return redirect(url_for("game.support_tickets"))

@bp.route("/support/reopen/<int:ticket_id>", methods=["POST"])
@login_required
def support_reopen(ticket_id):
    """Переоткрытие тикета"""
    manager_id = session["manager_id"]
    
    ticket = query_one("SELECT * FROM support_tickets WHERE id = ? AND manager_id = ?", 
                       (ticket_id, manager_id))
    if not ticket:
        flash("Тикет не найден", "error")
        return redirect(url_for("game.support"))
    
    execute("""
        UPDATE support_tickets 
        SET status = 'open', updated_at = datetime('now')
        WHERE id = ?
    """, (ticket_id,))
    
    admins = query_all("SELECT id FROM managers WHERE role='admin'")
    for admin in admins:
        notify(admin["id"], 
               f"🔄 Тикет #{ticket_id} переоткрыт менеджером",
               "/game/support-tickets")
    
    flash("✅ Тикет переоткрыт", "success")
    return redirect(url_for("game.support"))

@bp.route("/support/unread")
@login_required
def support_unread():
    """API для получения количества непрочитанных сообщений"""
    role = session.get("role")
    manager_id = session["manager_id"]
    
    if role == "admin":
        count = query_one("""
            SELECT COUNT(*) as c FROM support_messages 
            WHERE is_from_admin = 0 AND is_read = 0
        """)
    else:
        count = query_one("""
            SELECT COUNT(*) as c FROM support_messages 
            WHERE manager_id = ? AND is_from_admin = 1 AND is_read = 0
        """, (manager_id,))
    
    return jsonify({"unread": count["c"] if count else 0})
