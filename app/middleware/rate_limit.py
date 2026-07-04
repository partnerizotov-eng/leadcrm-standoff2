# app/middleware/rate_limit.py
from flask import request, jsonify
from functools import wraps
from collections import defaultdict
import time

class RateLimiter:
    _requests = defaultdict(list)
    
    @classmethod
    def limit(cls, max_requests=10, window_seconds=60):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                key = f"{request.remote_addr}:{func.__name__}"
                now = time.time()
                window_start = now - window_seconds
                
                # Очищаем старые запросы
                cls._requests[key] = [req for req in cls._requests[key] if req > window_start]
                
                if len(cls._requests[key]) >= max_requests:
                    return jsonify({"error": "Превышен лимит запросов"}), 429
                
                cls._requests[key].append(now)
                return func(*args, **kwargs)
            return wrapper
        return decorator