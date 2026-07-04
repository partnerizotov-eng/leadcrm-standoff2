"""Standoff 2 интеграция - ручной режим"""
import json
from datetime import datetime
from flask import current_app
from .db import execute, query_one, query_all
from .notifications import notify

class Standoff2API:
    """Клиент для работы с Standoff 2 (ручной режим)"""
    
    def __init__(self):
        self.base_url = "https://api.standoff2.com/v1"
        self.api_key = ""
        self.secret = ""
    
    def init_config(self):
        self.api_key = current_app.config.get("STANDOFF2_API_KEY", "")
        self.secret = current_app.config.get("STANDOFF2_SECRET", "")
    
    def verify_player(self, game_id):
        """Проверка существования игрока - ручной режим"""
        # В ручном режиме считаем, что любой ID валидный
        # Менеджер сам проверяет, что ID правильный
        return {
            "name": f"Игрок_{game_id[:8]}",
            "exists": True,
            "game_id": game_id
        }
    
    def get_player_stats(self, game_id):
        """Получение статистики игрока - заглушка"""
        return {
            "rank": "Новичок",
            "level": 0,
            "hours_played": 0,
            "kd_ratio": 0,
            "wins": 0
        }
    
    def get_player_rank(self, game_id):
        """Получение ранга"""
        return "Неизвестно"
    
    def send_gold(self, game_id, amount, reason=""):
        """Отправка голды - заглушка"""
        # В реальном API здесь была бы отправка
        # Сейчас просто возвращаем успех
        return f"tx_{game_id[:6]}_{int(datetime.now().timestamp())}"
    
    def check_gold_balance(self, game_id):
        """Проверка баланса - заглушка"""
        return 0


class Standoff2Manager:
    """Менеджер для работы с Standoff 2"""
    
    def __init__(self):
        self.api = Standoff2API()
    
    def link_game_account(self, lead_id, game_id, manager_id):
        """Привязка игрового аккаунта к лиду"""
        # Проверка на дубликат
        existing = query_one(
            "SELECT id FROM leads WHERE game_id = ? AND id != ?",
            (game_id, lead_id)
        )
        if existing:
            return False, "Этот игровой ID уже привязан к другому лиду"
        
        # Получение информации (заглушка)
        player = self.api.verify_player(game_id)
        rank = self.api.get_player_rank(game_id)
        stats = self.api.get_player_stats(game_id)
        
        # Обновление лида
        execute("""
            UPDATE leads 
            SET game_id = ?, 
                game_rank = ?, 
                game_stats = ?,
                game_verified = 1,
                game_verified_at = datetime('now'),
                name = COALESCE(name, ?)
            WHERE id = ?
        """, (game_id, rank, json.dumps(stats), player.get("name", ""), lead_id))
        
        # Обновление game_accounts таблицы
        execute("""
            INSERT OR REPLACE INTO game_accounts (
                lead_id, game_id, game_name, platform, 
                rank, level, hours_played, kd_ratio, wins,
                stats, verified, verified_at
            ) VALUES (?, ?, ?, 'standoff2', ?, ?, ?, ?, ?, ?, 1, datetime('now'))
        """, (lead_id, game_id, player.get("name", ""), rank, 
              stats.get("level", 0), stats.get("hours_played", 0),
              stats.get("kd_ratio", 0), stats.get("wins", 0),
              json.dumps(stats)))
        
        # Логирование
        execute("""
            INSERT INTO activity (manager_id, message)
            VALUES (?, ?)
        """, (manager_id, f"Привязан игровой аккаунт {game_id} (ранг: {rank})"))
        
        return True, "✅ Аккаунт успешно привязан! Убедитесь, что ID правильный."
    
    def withdraw_gold_to_game(self, lead_id, amount, manager_id):
        """Вывод голды в игру"""
        lead = query_one("SELECT * FROM leads WHERE id = ?", (lead_id,))
        if not lead:
            return False, "Лид не найден"
        
        if not lead["game_id"]:
            return False, "Игровой аккаунт не привязан"
        
        if lead["balance"] < amount:
            return False, f"Недостаточно голды. Доступно: {lead['balance']:.2f}G"
        
        if amount < 10:
            return False, "Минимальная сумма вывода - 10G"
        
        # Отправка голды (заглушка)
        transaction_id = self.api.send_gold(
            lead["game_id"],
            amount,
            f"Вывод из Lead CRM, менеджер #{manager_id}"
        )
        
        if not transaction_id:
            return False, "Ошибка при отправке голды"
        
        # Обновление баланса в CRM
        from . import db
        with db.transaction() as conn:
            conn.execute(
                "UPDATE leads SET balance = balance - ? WHERE id = ?",
                (amount, lead_id)
            )
            
            conn.execute("""
                INSERT INTO balance_ledger (
                    lead_id, amount, reason, reference_id, note
                ) VALUES (?, ?, 'game_withdraw', ?, ?)
            """, (lead_id, -amount, transaction_id, f"Вывод в Standoff 2"))
            
            conn.execute("""
                INSERT INTO game_withdrawals (
                    lead_id, manager_id, game_id, amount, 
                    transaction_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'completed', datetime('now'))
            """, (lead_id, manager_id, lead["game_id"], amount, transaction_id))
        
        # Уведомление
        notify(manager_id, 
               f"✅ Вывод {amount}G в игру для {lead['name']} выполнен!",
               "/game/withdrawals")
        
        return True, f"✅ Вывод {amount}G успешно выполнен! ID транзакции: {transaction_id[:12]}..."