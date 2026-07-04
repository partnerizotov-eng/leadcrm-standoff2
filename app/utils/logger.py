"""Расширенное логирование"""
import logging
import json
from datetime import datetime
from flask import request, session

class AppLogger:
    def __init__(self):
        self.logger = logging.getLogger('leadcrm')
        self.logger.setLevel(logging.DEBUG)
        
        # Форматтер
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Файловый обработчик
        fh = logging.FileHandler('logs/app.log')
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
    
    def log_action(self, action, details=None, user_id=None):
        """Логирование действий"""
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'user_id': user_id or session.get('manager_id'),
            'ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent'),
            'details': details
        }
        self.logger.info(json.dumps(log_data, ensure_ascii=False))
    
    def log_error(self, error, context=None):
        """Логирование ошибок"""
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'error': str(error),
            'context': context,
            'user_id': session.get('manager_id'),
            'ip': request.remote_addr
        }
        self.logger.error(json.dumps(log_data, ensure_ascii=False))

logger = AppLogger()