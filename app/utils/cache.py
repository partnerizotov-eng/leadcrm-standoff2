"""Кеширование для ускорения работы"""
import time
import json
from functools import wraps
from flask import current_app

class Cache:
    """Простой кеш в памяти"""
    _cache = {}
    
    @classmethod
    def get(cls, key):
        data = cls._cache.get(key)
        if data and data.get('expires', 0) > time.time():
            return data.get('value')
        if data:
            del cls._cache[key]
        return None
    
    @classmethod
    def set(cls, key, value, ttl=300):
        cls._cache[key] = {
            'value': value,
            'expires': time.time() + ttl
        }
    
    @classmethod
    def delete(cls, key):
        cls._cache.pop(key, None)
    
    @classmethod
    def clear(cls):
        cls._cache.clear()

def cached(ttl=300):
    """Декоратор для кеширования"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Генерируем ключ
            key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            cached = Cache.get(key)
            if cached is not None:
                return cached
            
            result = func(*args, **kwargs)
            Cache.set(key, result, ttl)
            return result
        return wrapper
    return decorator
