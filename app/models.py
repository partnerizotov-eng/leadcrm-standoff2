"""Модели данных для Lead CRM"""
import json
from datetime import datetime
from .db import query_one, query_all, execute

class GameAccount:
    """Модель игрового аккаунта"""
    
    def __init__(self, data):
        self.id = data.get("id")
        self.lead_id = data.get("lead_id")
        self.game_id = data.get("game_id")
        self.game_name = data.get("game_name", "")
        self.platform = data.get("platform", "standoff2")
        self.rank = data.get("rank", "Новичок")
        self.level = data.get("level", 0)
        self.hours_played = data.get("hours_played", 0)
        self.kd_ratio = data.get("kd_ratio", 0)
        self.wins = data.get("wins", 0)
        self.balance = data.get("balance", 0)
        self.verified = data.get("verified", False)
        self.verified_at = data.get("verified_at")
        self.created_at = data.get("created_at")
        self.updated_at = data.get("updated_at")
        self.stats = json.loads(data.get("stats", "{}")) if data.get("stats") else {}
    
    @classmethod
    def get_by_lead_id(cls, lead_id):
        """Получение игрового аккаунта по ID лида"""
        data = query_one(
            "SELECT * FROM game_accounts WHERE lead_id = ?",
            (lead_id,)
        )
        return cls(data) if data else None
    
    @classmethod
    def get_by_game_id(cls, game_id):
        """Получение по игровому ID"""
        data = query_one(
            "SELECT * FROM game_accounts WHERE game_id = ?",
            (game_id,)
        )
        return cls(data) if data else None
    
    def update_rank(self, rank):
        """Обновление ранга"""
        self.rank = rank
        execute(
            "UPDATE game_accounts SET rank = ?, updated_at = datetime('now') WHERE id = ?",
            (rank, self.id)
        )
    
    def update_balance(self, balance):
        """Обновление баланса голды в игре"""
        self.balance = balance
        execute(
            "UPDATE game_accounts SET balance = ?, updated_at = datetime('now') WHERE id = ?",
            (balance, self.id)
        )


class GoldWithdrawal:
    """Модель вывода голды"""
    
    def __init__(self, data):
        self.id = data.get("id")
        self.lead_id = data.get("lead_id")
        self.manager_id = data.get("manager_id")
        self.game_id = data.get("game_id")
        self.amount = data.get("amount", 0)
        self.commission = data.get("commission", 0)
        self.net_amount = data.get("net_amount", 0)
        self.transaction_id = data.get("transaction_id")
        self.status = data.get("status", "pending")  # pending, processing, completed, failed
        self.error_message = data.get("error_message", "")
        self.created_at = data.get("created_at")
        self.processed_at = data.get("processed_at")
        self.completed_at = data.get("completed_at")
    
    @classmethod
    def create(cls, lead_id, manager_id, game_id, amount, commission=0):
        """Создание заявки на вывод"""
        net_amount = amount - commission
        
        withdrawal_id = execute("""
            INSERT INTO game_withdrawals (
                lead_id, manager_id, game_id, amount, 
                commission, net_amount, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', datetime('now'))
        """, (lead_id, manager_id, game_id, amount, commission, net_amount))
        
        return cls.get_by_id(withdrawal_id)
    
    @classmethod
    def get_by_id(cls, withdrawal_id):
        """Получение по ID"""
        data = query_one(
            "SELECT * FROM game_withdrawals WHERE id = ?",
            (withdrawal_id,)
        )
        return cls(data) if data else None
    
    @classmethod
    def get_by_manager_id(cls, manager_id, limit=50):
        """Получение выводов менеджера"""
        data = query_all("""
            SELECT * FROM game_withdrawals 
            WHERE manager_id = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (manager_id, limit))
        return [cls(row) for row in data]
    
    def process(self):
        """Обработка вывода (отправка в игру)"""
        if self.status != "pending":
            return False, "Вывод уже обработан"
        
        self.status = "processing"
        self.processed_at = datetime.now().isoformat()
        execute("""
            UPDATE game_withdrawals 
            SET status = 'processing', processed_at = datetime('now')
            WHERE id = ?
        """, (self.id,))
        
        # Здесь должна быть отправка в Standoff 2 API
        from .standoff2 import standoff2
        transaction_id = standoff2.api.send_gold(
            self.game_id,
            self.net_amount,
            f"Вывод из Lead CRM #{self.id}"
        )
        
        if transaction_id:
            self.complete(transaction_id)
            return True, "Вывод успешно выполнен"
        else:
            self.fail("Ошибка при отправке в Standoff 2")
            return False, "Ошибка при отправке"
    
    def complete(self, transaction_id):
        """Завершение вывода"""
        self.status = "completed"
        self.transaction_id = transaction_id
        self.completed_at = datetime.now().isoformat()
        execute("""
            UPDATE game_withdrawals 
            SET status = 'completed', transaction_id = ?, completed_at = datetime('now')
            WHERE id = ?
        """, (transaction_id, self.id))
    
    def fail(self, error_message):
        """Отмена вывода"""
        self.status = "failed"
        self.error_message = error_message
        execute("""
            UPDATE game_withdrawals 
            SET status = 'failed', error_message = ?
            WHERE id = ?
        """, (error_message, self.id))


class ManagerStats:
    """Модель статистики менеджера"""
    
    def __init__(self, manager_id):
        self.manager_id = manager_id
    
    def get_dashboard(self):
        """Получение дашборда менеджера"""
        stats = query_one("""
            SELECT 
                m.id,
                m.name,
                m.balance,
                m.total_earned,
                COUNT(DISTINCT l.id) as total_leads,
                COUNT(DISTINCT CASE WHEN l.status IN ('participated', 'returning') THEN l.id END) as converted_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'new' THEN l.id END) as new_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'contacted' THEN l.id END) as contacted_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'replied' THEN l.id END) as replied_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'joined_channel' THEN l.id END) as joined_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'participated' THEN l.id END) as participated_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'returning' THEN l.id END) as returning_leads,
                COUNT(DISTINCT s.id) as total_submissions,
                COUNT(DISTINCT CASE WHEN s.status = 'approved' THEN s.id END) as approved_submissions,
                COUNT(DISTINCT CASE WHEN s.status = 'rejected' THEN s.id END) as rejected_submissions,
                COALESCE(SUM(CASE WHEN s.status = 'approved' THEN 10 ELSE 0 END), 0) as earnings_from_submissions,
                COALESCE(SUM(CASE WHEN s.status = 'rejected' THEN 1 ELSE 0 END), 0) as penalties,
                COUNT(DISTINCT w.id) as total_withdrawals,
                COALESCE(SUM(w.amount), 0) as total_withdrawn,
                COALESCE(ROUND(CAST(COUNT(DISTINCT CASE WHEN l.status IN ('participated', 'returning') THEN l.id END) AS REAL) / 
                NULLIF(COUNT(DISTINCT l.id), 0) * 100, 1), 0) as conversion_pct
            FROM managers m
            LEFT JOIN leads l ON l.assigned_manager_id = m.id
            LEFT JOIN submissions s ON s.manager_id = m.id
            LEFT JOIN game_withdrawals w ON w.manager_id = m.id
            WHERE m.id = ?
            GROUP BY m.id
        """, (self.manager_id,))
        
        if stats:
            return dict(stats)
        return None
    
    def get_rank(self):
        """Получение позиции в рейтинге"""
        stats = self.get_dashboard()
        if not stats:
            return None
        
        better_count = query_one("""
            SELECT COUNT(*) as c FROM (
                SELECT m.id,
                    COALESCE(ROUND(CAST(COUNT(DISTINCT CASE WHEN l.status IN ('participated', 'returning') THEN l.id END) AS REAL) / 
                    NULLIF(COUNT(DISTINCT l.id), 0) * 100, 1), 0) as conversion_pct
                FROM managers m
                LEFT JOIN leads l ON l.assigned_manager_id = m.id
                WHERE m.role = 'manager'
                GROUP BY m.id
                HAVING conversion_pct > ?
            )
        """, (stats["conversion_pct"],))
        
        rank = (better_count["c"] if better_count else 0) + 1
        return rank
    
    def get_daily_goals(self):
        """Получение дневных целей"""
        today = datetime.now().date().isoformat()
        
        goals = {
            "leads_target": 5,
            "submissions_target": 3,
            "conversion_target": 30
        }
        
        achieved = query_one("""
            SELECT 
                COUNT(DISTINCT l.id) as leads_today,
                COUNT(DISTINCT s.id) as submissions_today,
                COALESCE(ROUND(CAST(COUNT(DISTINCT CASE WHEN l.status IN ('participated', 'returning') THEN l.id END) AS REAL) / 
                NULLIF(COUNT(DISTINCT l.id), 0) * 100, 1), 0) as conversion_today
            FROM managers m
            LEFT JOIN leads l ON l.assigned_manager_id = m.id AND DATE(l.found_at) = DATE('now')
            LEFT JOIN submissions s ON s.manager_id = m.id AND DATE(s.created_at) = DATE('now')
            WHERE m.id = ?
        """, (self.manager_id,))
        
        return {
            "leads": {
                "target": goals["leads_target"],
                "achieved": achieved["leads_today"] if achieved else 0
            },
            "submissions": {
                "target": goals["submissions_target"],
                "achieved": achieved["submissions_today"] if achieved else 0
            },
            "conversion": {
                "target": goals["conversion_target"],
                "achieved": achieved["conversion_today"] if achieved else 0
            }
        }