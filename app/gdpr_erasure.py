"""Удаление персональных данных лида по запросу — 152-ФЗ / право на забвение.

В отличие от app.admin_leads.delete_lead (модерационное удаление с архивом
и возможностью восстановления — используется, когда лид оказался мусорным
или дублем), это НЕОБРАТИМО и не сохраняет vk_id/имя нигде, даже в логах.
Это и есть смысл права на забвение: после удаления не должно остаться
способа восстановить, кем был этот человек.

Используйте delete_lead() для обычной модерации. Эту функцию — только
по прямому запросу человека на удаление его персональных данных.
"""
from .db import query_one, transaction, log_activity


def find_lead_for_erasure(query: str):
    """Ищет лида по vk_id / части ссылки / имени — для показа админу перед
    удалением (подтверждение «это тот самый человек»)."""
    query = (query or "").strip()
    if not query:
        return []
    from .db import query_all
    from .utils.vk_validator import VKValidator
    vk_id = VKValidator.extract_id(query)

    if vk_id:
        rows = query_all(
            "SELECT id, name, vk_id, vk_url, status, found_at FROM leads "
            "WHERE vk_id = ? OR vk_id LIKE ? OR name LIKE ?",
            (vk_id, f"%{vk_id}%", f"%{query}%"))
    else:
        rows = query_all(
            "SELECT id, name, vk_id, vk_url, status, found_at FROM leads "
            "WHERE name LIKE ? OR vk_url LIKE ?",
            (f"%{query}%", f"%{query}%"))
    return [dict(r) for r in rows]


def erase_lead_data(lead_id: int, admin_id: int, reason: str = ""):
    """Безвозвратно удаляет лида и все связанные записи (каскадом через
    внешние ключи: submissions, balance_ledger, участия, история статусов,
    игровые аккаунты и выводы). Ничего не восстановить — это осознанно.

    В аудит-лог (activity) пишется только факт и id — БЕЗ vk_id и имени,
    иначе смысл права на забвение теряется.
    """
    lead = query_one("SELECT id FROM leads WHERE id=?", (lead_id,))
    if not lead:
        return False, "Лид не найден (возможно, уже удалён)."

    with transaction() as db:
        db.execute("DELETE FROM leads WHERE id=?", (lead_id,))

    note = f"152-ФЗ: персональные данные лида #{lead_id} удалены безвозвратно по запросу"
    if reason.strip():
        note += f" — {reason.strip()}"
    log_activity(note, manager_id=admin_id)

    return True, "Данные удалены безвозвратно. Восстановить невозможно."
