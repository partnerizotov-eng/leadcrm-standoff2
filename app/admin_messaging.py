"""Массовая отправка уведомлений менеджерам — всем или выборочно."""
from .db import execute, query_all


def send_mass_message(manager_ids, message):
    """Отправить уведомление списку менеджеров.
    manager_ids=None -> отправить всем менеджерам."""
    if not manager_ids:
        rows = query_all("SELECT id FROM managers WHERE role='manager'")
        manager_ids = [r['id'] for r in rows]

    count = 0
    for mid in manager_ids:
        execute("INSERT INTO notifications (manager_id, message, created_at) VALUES (?, ?, datetime('now'))",
                (mid, message))
        count += 1
    return count
