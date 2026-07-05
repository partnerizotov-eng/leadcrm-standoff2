"""Управление балансом менеджеров"""
from .db import execute, query_one, query_all


def add_balance(manager_id, amount, reason, admin_id):
    """Добавить голду менеджеру"""
    
    manager = query_one("SELECT * FROM managers WHERE id = ?", (manager_id,))
    if not manager:
        return False, "❌ Менеджер не найден"
    
    execute("UPDATE managers SET balance = balance + ? WHERE id = ?", (amount, manager_id))
    
    execute("""
        INSERT INTO balance_logs (manager_id, amount_change, reason, admin_id, created_at)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, (manager_id, amount, reason, admin_id))
    
    message = f"✅ Ваш баланс пополнен на {amount}G. Причина: {reason}"
    execute("INSERT INTO notifications (manager_id, message, created_at) VALUES (?, ?, datetime('now'))",
            (manager_id, message))
    
    return True, f"✅ Добавлено {amount}G менеджеру {manager['name']}"


def subtract_balance(manager_id, amount, reason, admin_id):
    """Убрать голду у менеджера"""
    
    manager = query_one("SELECT * FROM managers WHERE id = ?", (manager_id,))
    if not manager:
        return False, "❌ Менеджер не найден"
    
    balance = manager['balance'] or 0
    if balance < amount:
        return False, f"❌ Недостаточно голды. Баланс: {balance}G"
    
    execute("UPDATE managers SET balance = balance - ? WHERE id = ?", (amount, manager_id))
    
    execute("""
        INSERT INTO balance_logs (manager_id, amount_change, reason, admin_id, created_at)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, (manager_id, -amount, reason, admin_id))
    
    message = f"❌ Ваш баланс уменьшен на {amount}G. Причина: {reason}"
    execute("INSERT INTO notifications (manager_id, message, created_at) VALUES (?, ?, datetime('now'))",
            (manager_id, message))
    
    return True, f"✅ Вычтено {amount}G у менеджера {manager['name']}"


def get_balance_logs(limit=50):
    """Получить историю операций с балансом"""
    sql = """
        SELECT bl.*, m.name as manager_name, a.name as admin_name
        FROM balance_logs bl
        JOIN managers m ON bl.manager_id = m.id
        JOIN managers a ON bl.admin_id = a.id
        ORDER BY bl.created_at DESC
        LIMIT ?
    """
    return query_all(sql, (limit,))
