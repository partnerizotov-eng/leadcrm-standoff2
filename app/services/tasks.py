"""Фоновые задачи"""
import threading
import time
from datetime import datetime, timedelta
from app.db import execute, query_all
from app.notifications import notify
from app.utils.logger import logger

class BackgroundTasks:
    @staticmethod
    def send_daily_reminders():
        """Ежедневные напоминания"""
        while True:
            try:
                # Проверяем время (12:00, 18:00, 00:00)
                now = datetime.now()
                if now.hour in [12, 18, 0] and now.minute == 0:
                    # Уведомление менеджерам о конкурсе
                    managers = query_all("SELECT id FROM managers WHERE role='manager' AND is_active=1")
                    for manager in managers:
                        notify(manager["id"], 
                               "🎁 Напоминание! Через 30 минут стартует конкурс с призом 50 голды!",
                               "/leads")
                    logger.log_action("daily_reminder", "Отправлены напоминания о конкурсе")
                
                time.sleep(60)  # Проверка каждую минуту
            except Exception as e:
                logger.log_error(e, "daily_reminder")
                time.sleep(300)  # Пауза при ошибке
    
    @staticmethod
    def cleanup_old_data():
        """Очистка старых данных"""
        while True:
            try:
                # Удаляем старые уведомления (старше 30 дней)
                execute("""
                    DELETE FROM notifications 
                    WHERE created_at < datetime('now', '-30 days')
                    AND is_read = 1
                """)
                
                # Архивация старых логов
                execute("""
                    DELETE FROM activity 
                    WHERE created_at < datetime('now', '-90 days')
                """)
                
                time.sleep(86400)  # Раз в сутки
            except Exception as e:
                logger.log_error(e, "cleanup_old_data")
                time.sleep(3600)

def start_background_tasks():
    """Запуск фоновых задач"""
    thread = threading.Thread(target=BackgroundTasks.send_daily_reminders, daemon=True)
    thread.start()
    
    cleanup_thread = threading.Thread(target=BackgroundTasks.cleanup_old_data, daemon=True)
    cleanup_thread.start()