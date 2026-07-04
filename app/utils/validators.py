"""Валидация входных данных"""
import re

class Validator:
    @staticmethod
    def validate_vk_url(url):
        """Проверка VK URL"""
        if not url:
            return False, "Ссылка не может быть пустой"
        
        url = url.strip()
        
        # Паттерны для разных форматов VK ссылок
        patterns = [
            r'^https?://(www\.|m\.)?vk\.com/(id[0-9]+|[a-zA-Z0-9_\.]+)/?$',
            r'^vk\.com/(id[0-9]+|[a-zA-Z0-9_\.]+)/?$',
            r'^(id[0-9]+|[a-zA-Z0-9_\.]+)$',
            r'^@(id[0-9]+|[a-zA-Z0-9_\.]+)$',
        ]
        
        for pattern in patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return True, "Ссылка валидна"
        
        return False, "Неверный формат ссылки VK"
    
    @staticmethod
    def validate_game_id(game_id):
        """Проверка игрового ID"""
        if not game_id:
            return False, "ID не может быть пустым"
        return True, "ID валиден"
    
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
