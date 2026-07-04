"""Валидация входных данных"""
import re
from datetime import datetime

class Validator:
    @staticmethod
    def validate_vk_url(url):
        """Проверка VK URL"""
        patterns = [
            r'^https?://(www\.)?vk\.com/',
            r'^vk\.com/',
            r'^@?[a-zA-Z0-9_\.]+$'
        ]
        return any(re.match(p, url) for p in patterns)
    
    @staticmethod
    def validate_game_id(game_id):
        """Проверка игрового ID Standoff 2"""
        return bool(re.match(r'^[a-zA-Z0-9_]{3,32}$', game_id))
    
    @staticmethod
    def validate_amount(amount, min_amount=0, max_amount=None):
        """Проверка суммы"""
        try:
            amount = float(amount)
            if amount < min_amount:
                return False, f"Минимальная сумма: {min_amount}"
            if max_amount and amount > max_amount:
                return False, f"Максимальная сумма: {max_amount}"
            return True, amount
        except ValueError:
            return False, "Некорректная сумма"
    
    @staticmethod
    def validate_status(status, allowed_statuses):
        """Проверка статуса"""
        return status in allowed_statuses
    
    @staticmethod
    def sanitize_text(text):
        """Очистка текста от XSS"""
        import html
        return html.escape(text.strip())