"""Оптимизация запросов к БД"""
import sqlite3
from functools import lru_cache
from flask import current_app

class DBManager:
    @staticmethod
    def get_connection():
        return sqlite3.connect(current_app.config["DATABASE_PATH"])
    
    @staticmethod
    @lru_cache(maxsize=100)
    def get_stats():
        """Кешированная статистика"""
        conn = DBManager.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        tables = ['managers', 'leads', 'submissions', 'withdrawals', 'scripts']
        
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]
        
        conn.close()
        return stats
    
    @staticmethod
    def optimize_db():
        """Оптимизация БД"""
        conn = DBManager.get_connection()
        cursor = conn.cursor()
        
        # Анализ
        cursor.execute("ANALYZE")
        
        # Вакуум
        cursor.execute("VACUUM")
        
        # Пересоздание индексов
        cursor.execute("REINDEX")
        
        conn.close()
        return "✅ База данных оптимизирована"

# Создаем индексы для ускорения
def create_optimized_indexes():
    conn = DBManager.get_connection()
    cursor = conn.cursor()
    
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_leads_status_created ON leads(status, found_at)",
        "CREATE INDEX IF NOT EXISTS idx_leads_manager_status ON leads(assigned_manager_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_submissions_status_created ON submissions(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_outreach_log_manager ON outreach_log(manager_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_manager_read ON notifications(manager_id, is_read)",
    ]
    
    for idx in indexes:
        cursor.execute(idx)
    
    conn.commit()
    conn.close()