"""Тикеты поддержки — полноценный чат менеджер <-> админ с вложениями."""
from .db import execute, query_one, query_all


def send_support_message(ticket_id, sender_id, message_text, is_admin=False,
                          attachment_path=None, attachment_type=None):
    """Отправить сообщение в чат тикета. Текст может быть пустым, если есть вложение."""

    ticket = query_one("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
    if not ticket:
        return False, "❌ Тикет не найден"

    if not message_text and not attachment_path:
        return False, "❌ Пустое сообщение"

    execute("""
        INSERT INTO support_messages (ticket_id, manager_id, admin_id, message, is_from_admin,
                                       attachment_path, attachment_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (ticket_id, ticket['manager_id'], sender_id if is_admin else None,
          message_text or "", 1 if is_admin else 0, attachment_path, attachment_type))

    execute("UPDATE support_tickets SET updated_at = datetime('now') WHERE id = ?", (ticket_id,))

    sender = query_one("SELECT * FROM managers WHERE id = ?", (sender_id,))
    preview = message_text[:50] if message_text else "📎 Вложение"

    if is_admin:
        notification_msg = f"💬 Админ ответил в тикете: \"{preview}\""
        execute("INSERT INTO notifications (manager_id, message, created_at) VALUES (?, ?, datetime('now'))",
                (ticket['manager_id'], notification_msg))
    else:
        notification_msg = f"💬 {sender['name']} написал в тикете: \"{preview}\""
        admin = query_one("SELECT id FROM managers WHERE role = 'admin' LIMIT 1")
        if admin:
            execute("INSERT INTO notifications (manager_id, message, created_at) VALUES (?, ?, datetime('now'))",
                    (admin['id'], notification_msg))

    return True, "✅ Сообщение отправлено"


def get_ticket_messages(ticket_id):
    """Получить все сообщения тикета (с вложениями)."""
    sql = """
        SELECT sm.*,
               COALESCE(m.name, a.name) as sender_name,
               CASE WHEN sm.is_from_admin = 1 THEN 'admin' ELSE 'manager' END as sender_role
        FROM support_messages sm
        LEFT JOIN managers m ON sm.manager_id = m.id AND sm.is_from_admin = 0
        LEFT JOIN managers a ON sm.admin_id = a.id AND sm.is_from_admin = 1
        WHERE sm.ticket_id = ?
        ORDER BY sm.created_at ASC
    """
    return query_all(sql, (ticket_id,))


def close_ticket(ticket_id):
    """Закрыть тикет."""
    ticket = query_one("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
    if not ticket:
        return False, "❌ Тикет не найден"
    execute("UPDATE support_tickets SET status = 'closed', closed_at = datetime('now') WHERE id = ?", (ticket_id,))
    return True, "✅ Тикет закрыт"


def create_ticket(manager_id, subject, first_message):
    """Создать новый тикет — сразу начинает чат первым сообщением менеджера."""
    ticket_id = execute("""
        INSERT INTO support_tickets (manager_id, subject, status, created_at)
        VALUES (?, ?, 'open', datetime('now'))
    """, (manager_id, subject))

    execute("""
        INSERT INTO support_messages (ticket_id, manager_id, message, is_from_admin, created_at)
        VALUES (?, ?, ?, 0, datetime('now'))
    """, (ticket_id, manager_id, first_message))

    admin = query_one("SELECT id FROM managers WHERE role = 'admin' LIMIT 1")
    if admin:
        notification_msg = f"🆘 Новый тикет поддержки: {subject}"
        execute("INSERT INTO notifications (manager_id, message, created_at) VALUES (?, ?, datetime('now'))",
                (admin['id'], notification_msg))

    return ticket_id
