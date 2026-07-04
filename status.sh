#!/bin/bash
echo "📊 Статус Lead CRM"

# Проверка сервера
if curl -s http://127.0.0.1:5100/healthz | grep -q "ok"; then
    echo "✅ Сервер работает"
else
    echo "❌ Сервер не отвечает"
fi

# Статистика БД
echo ""
echo "📊 Статистика базы данных:"
sqlite3 data/leadcrm.db "SELECT 'Лиды: ' || COUNT(*) FROM leads;"
sqlite3 data/leadcrm.db "SELECT 'Менеджеры: ' || COUNT(*) FROM managers WHERE role='manager';"
sqlite3 data/leadcrm.db "SELECT 'Заявки: ' || COUNT(*) FROM submissions;"
sqlite3 data/leadcrm.db "SELECT 'Выводы: ' || COUNT(*) FROM game_withdrawals;"

# Проверка свободного места
echo ""
echo "💾 Свободное место:"
df -h . | tail -1 | awk '{print "Доступно: " $4}'

# Проверка размера БД
echo ""
echo "📦 Размер БД:"
ls -lh data/leadcrm.db | awk '{print $5}'
