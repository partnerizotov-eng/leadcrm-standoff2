"""Валидатор VK ссылок"""
import re

class VKValidator:
    @staticmethod
    def is_valid_vk_url(url, check_exists=False):
        """Проверка VK ссылки"""
        if not url or not url.strip():
            return False, "Ссылка не может быть пустой"
        
        url = url.strip()
        
        # Паттерны для разных форматов. vk.com и vk.ru — оба валидны как ввод
        # (vk.com по факту редиректит на vk.ru, но встречается в старых ссылках).
        patterns = [
            r'^https?://(www\.|m\.)?vk\.(com|ru)/(id[0-9]+|[a-zA-Z0-9_\.]+)/?$',
            r'^vk\.(com|ru)/(id[0-9]+|[a-zA-Z0-9_\.]+)/?$',
            r'^(id[0-9]+|[a-zA-Z0-9_\.]+)$',
            r'^@(id[0-9]+|[a-zA-Z0-9_\.]+)$',
        ]
        
        for pattern in patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return True, "Валидная ссылка VK"
        
        return False, "Неверный формат ссылки VK"
    
    @staticmethod
    def extract_id(url):
        """Извлечение VK ID из ссылки"""
        url = url.strip()
        clean_url = re.sub(r'^https?://(www\.|m\.)?', '', url)
        clean_url = re.sub(r'^vk\.(com|ru)/', '', clean_url)
        clean_url = clean_url.lstrip('@').rstrip('/')
        
        if re.match(r'^[a-zA-Z0-9_\.]+$', clean_url):
            return clean_url
        return None
