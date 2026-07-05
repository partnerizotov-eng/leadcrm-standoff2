"""Скрипты для переписки с лидами"""
from .db import execute, query_one, query_all

DEFAULT_SCRIPTS = [
    {'title': 'Приветствие новому лиду', 'text': 'Привет! 👋 Я менеджер проекта. У нас есть отличные возможности для заработка. Готов рассказать подробнее?', 'category': 'greeting'},
    {'title': 'Напоминание', 'text': 'Привет! Заметил, что давно не заходил. Есть новые интересные предложения! Заглянешь? 💰', 'category': 'follow_up'},
    {'title': 'Спецпредложение', 'text': 'Только для тебя! 🎁 Сейчас есть бонус +100G за первый вывод. Интересует?', 'category': 'offer'},
    {'title': 'Предупреждение', 'text': '⚠️ Заметили подозрительную активность на твоём аккаунте. Свяжись с админом срочно!', 'category': 'warning'},
    {'title': 'Завершение', 'text': 'Спасибо за участие! Если будут вопросы - всегда готов помочь. Удачи! 🚀', 'category': 'closing'},
    {'title': 'Срочно требуется помощь', 'text': 'Срочно нужна помощь! У нас есть спец задание с хорошим вознаграждением. Свободен? 💎', 'category': 'offer'}
]


def init_default_scripts(admin_id):
    """Инициализировать предустановленные скрипты"""
    existing = query_one("SELECT COUNT(*) as cnt FROM message_scripts")
    if existing['cnt'] > 0:
        return
    
    for script_data in DEFAULT_SCRIPTS:
        execute("""
            INSERT INTO message_scripts (title, text, category, created_by, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, datetime('now'))
        """, (script_data['title'], script_data['text'], script_data['category'], admin_id))


def get_all_scripts():
    """Получить все активные скрипты"""
    return query_all("SELECT * FROM message_scripts WHERE is_active = 1 ORDER BY category")


def create_script(title, text, category, creator_id):
    """Создать новый скрипт"""
    execute("""
        INSERT INTO message_scripts (title, text, category, created_by, is_active, created_at)
        VALUES (?, ?, ?, ?, 1, datetime('now'))
    """, (title, text, category, creator_id))
    
    return True, f"✅ Скрипт '{title}' создан"


def use_script(script_id, manager_id, vk_id=None, lead_id=None):
    """Использовать скрипт (логировать)"""
    script = query_one("SELECT * FROM message_scripts WHERE id = ?", (script_id,))
    
    if not script:
        return False, "❌ Скрипт не найден", None
    
    execute("""
        INSERT INTO script_usage_logs (script_id, manager_id, lead_id, vk_id, used_at)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, (script_id, manager_id, lead_id, vk_id))
    
    return True, "✅ Скрипт скопирован", script['text']


def delete_script(script_id):
    """Удалить скрипт (мягкое удаление)"""
    script = query_one("SELECT * FROM message_scripts WHERE id = ?", (script_id,))
    
    if not script:
        return False, "❌ Скрипт не найден"
    
    execute("UPDATE message_scripts SET is_active = 0 WHERE id = ?", (script_id,))
    
    return True, f"✅ Скрипт '{script['title']}' удален"


def get_script_usage_count(script_id):
    """Получить количество использований скрипта"""
    result = query_one("SELECT COUNT(*) as cnt FROM script_usage_logs WHERE script_id = ?", (script_id,))
    return result['cnt'] if result else 0
