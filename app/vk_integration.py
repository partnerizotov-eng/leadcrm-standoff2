"""VK интеграция - прямой чат и профиль"""
from .db import query_one
import re


def get_vk_profile_url(vk_id):
    """Получить URL профиля VK по ID"""
    if not vk_id:
        return None
    
    if vk_id.startswith('http'):
        return vk_id
    
    if vk_id.isdigit():
        return f"https://vk.com/id{vk_id}"
    
    return f"https://vk.com/{vk_id}"


def get_direct_message_url(vk_id):
    """Получить URL для открытия прямого чата с пользователем VK"""
    if not vk_id:
        return None
    
    if vk_id.isdigit():
        return f"https://vk.me/{vk_id}"
    else:
        return f"https://vk.me/{vk_id}"


def parse_vk_id_from_input(vk_input):
    """Парсить VK ID из ссылки или ID"""
    if not vk_input:
        return None
    
    if vk_input.isdigit():
        return vk_input
    
    match = re.search(r'vk\.com/id(\d+)', vk_input)
    if match:
        return match.group(1)
    
    match = re.search(r'vk\.com/([a-z0-9_.]+)', vk_input)
    if match:
        return match.group(1)
    
    if not vk_input.startswith('http') and vk_input.replace('_', '').replace('.', '').isalnum():
        return vk_input
    
    return None


def find_lead_by_vk(vk_id):
    """Найти лида по VK ID"""
    if not vk_id:
        return None
    return query_one("SELECT * FROM leads WHERE vk_id = ?", (vk_id,))


def is_valid_vk_id(vk_id):
    """Проверить валидность VK ID"""
    if not vk_id:
        return False
    
    if vk_id.isdigit() and len(vk_id) > 0:
        return True
    
    if re.match(r'^[a-z0-9_.]+$', vk_id, re.IGNORECASE):
        return True
    
    return False
