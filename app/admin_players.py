"""Добавление голды игрокам (для топа)"""
from .db import execute, query_one, query_all
import re


def parse_vk_id(vk_input):
    """Парсит VK ссылку или ID"""
    if vk_input.isdigit():
        return vk_input
    
    match = re.search(r'vk\.com/(?:id)?(\d+)', vk_input)
    if match:
        return match.group(1)
    
    match = re.search(r'vk\.com/([a-z0-9_.]+)', vk_input)
    if match:
        return match.group(1)
    
    return None


def find_lead_by_vk(vk_id):
    """Находит лида по VK ID"""
    return query_one("SELECT * FROM leads WHERE vk_id = ?", (vk_id,))


def add_player_balance(vk_input, amount, reason, admin_id):
    """Добавить голду игроку по VK ID или ссылке"""
    
    vk_id = parse_vk_id(vk_input)
    if not vk_id:
        return False, "❌ Неверный формат VK ссылки или ID"
    
    lead = find_lead_by_vk(vk_id)
    if not lead:
        return False, f"❌ Лид с VK ID {vk_id} не найден"
    
    execute("UPDATE leads SET balance = balance + ? WHERE id = ?", (amount, lead['id']))
    
    execute("""
        INSERT INTO player_balance_logs (lead_id, vk_id, amount, reason, admin_id, created_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (lead['id'], vk_id, amount, reason, admin_id))
    
    return True, f"✅ Добавлено {amount}G игроку {lead['name']} (VK: {vk_id})"


def get_player_balance_logs(limit=50):
    """Получить историю добавления голды игрокам"""
    sql = """
        SELECT pbl.*, l.name as lead_name, a.name as admin_name
        FROM player_balance_logs pbl
        JOIN leads l ON pbl.lead_id = l.id
        JOIN managers a ON pbl.admin_id = a.id
        ORDER BY pbl.created_at DESC
        LIMIT ?
    """
    return query_all(sql, (limit,))
