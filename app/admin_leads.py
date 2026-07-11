"""Удаление лидов с уведомлением"""
from .db import execute, query_one, query_all


def delete_lead(lead_id, admin_comment, admin_id):
    """Удалить лида с уведомлением менеджеру"""
    
    lead = query_one("SELECT * FROM leads WHERE id = ?", (lead_id,))
    if not lead:
        return False, "❌ Лид не найден"
    
    lead_name = lead['name']
    lead_vk_id = lead['vk_id']
    manager_id = lead['assigned_manager_id']
    
    # Логируем удаление
    execute("""
        INSERT INTO deleted_leads_log (lead_id, lead_name, lead_vk_id, manager_id, admin_comment, admin_id, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (lead_id, lead_name, lead_vk_id, manager_id, admin_comment, admin_id))
    
    # Удаляем лида
    execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    
    # Уведомляем менеджера
    if manager_id:
        message = f"⚠️ Лид {lead_name} был удален администратором.\n\n📝 Комментарий: {admin_comment}"
        execute("INSERT INTO notifications (manager_id, message, created_at) VALUES (?, ?, datetime('now'))",
                (manager_id, message))
    
    return True, f"✅ Лид {lead_name} удалён. Менеджер уведомлен"


def get_deleted_leads(limit=50):
    """Получить архив удаленных лидов"""
    sql = """
        SELECT dl.*, m.name as manager_name, a.name as admin_name
        FROM deleted_leads_log dl
        LEFT JOIN managers m ON dl.manager_id = m.id
        JOIN managers a ON dl.admin_id = a.id
        ORDER BY dl.deleted_at DESC
        LIMIT ?
    """
    return query_all(sql, (limit,))


def restore_lead(log_id):
    """Восстановить лида из архива"""
    log = query_one("SELECT * FROM deleted_leads_log WHERE id = ?", (log_id,))
    if not log:
        return False, "❌ Запись об удалении не найдена"
    
    lead_id = execute("""
        INSERT INTO leads (name, vk_id, vk_url, assigned_manager_id, status)
        VALUES (?, ?, ?, ?, 'new')
    """, (log['lead_name'], log['lead_vk_id'], f"https://vk.ru/id{log['lead_vk_id']}", log['manager_id']))
    
    return True, f"✅ Лид {log['lead_name']} восстановлен"
