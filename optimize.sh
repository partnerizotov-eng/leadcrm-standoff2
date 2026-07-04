#!/bin/bash
echo "🚀 Оптимизация Lead CRM..."

# 1. Оптимизация БД
echo "📊 Оптимизация базы данных..."
sqlite3 data/leadcrm.db "VACUUM; ANALYZE; REINDEX;"

# 2. Очистка кеша Python
echo "🧹 Очистка кеша Python..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# 3. Проверка индексов
echo "🔍 Проверка индексов..."
sqlite3 data/leadcrm.db "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name NOT LIKE 'sqlite_%';"

# 4. Проверка целостности
echo "🔒 Проверка целостности БД..."
sqlite3 data/leadcrm.db "PRAGMA integrity_check;"

# 5. Очистка старых сессий
echo "🗑️ Очистка старых данных..."
sqlite3 data/leadcrm.db "DELETE FROM notifications WHERE created_at < datetime('now', '-30 days') AND is_read = 1;"
sqlite3 data/leadcrm.db "DELETE FROM activity WHERE created_at < datetime('now', '-90 days');"

# 6. Статистика
echo "📊 Статистика БД:"
sqlite3 data/leadcrm.db "SELECT 'Таблица ' || name || ': ' || COUNT(*) || ' записей' FROM sqlite_master JOIN pragma_table_info(name) GROUP BY name;"

echo "✅ Оптимизация завершена!"
