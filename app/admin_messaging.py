"""Массовая отправка уведомлений менеджерам — всем или выборочно."""
from .db import execute, query_all


def send_mass_message(manager_ids, message):
    """Отправить уведомление списку менеджеров.
    manager_ids=None -> отправить всем менеджерам.
    manager_ids=[] (явно пустой список, не None) -> никому не отправлять —
    это важно для сегментации: если сегмент ни под кого не подошёл, нельзя
    молча откатиться на "отправить всем" (было бы неожиданным и опасным)."""
    if manager_ids is None:
        rows = query_all("SELECT id FROM managers WHERE role='manager'")
        manager_ids = [r['id'] for r in rows]

    count = 0
    for mid in manager_ids:
        execute("INSERT INTO notifications (manager_id, message, created_at) VALUES (?, ?, datetime('now'))",
                (mid, message))
        count += 1
    return count
