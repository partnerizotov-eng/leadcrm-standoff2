#!/bin/bash
echo "💾 Создание бэкапа..."

# Создаем папку для бэкапов
mkdir -p backups

# Имя файла с датой
BACKUP_FILE="backups/leadcrm_$(date +%Y%m%d_%H%M%S).db"

# Копируем БД
cp data/leadcrm.db "$BACKUP_FILE"

# Сжимаем
gzip "$BACKUP_FILE"

echo "✅ Бэкап создан: ${BACKUP_FILE}.gz"

# Удаляем старые бэкапы (старше 7 дней)
find backups -name "*.gz" -mtime +7 -delete
echo "🗑️ Старые бэкапы удалены"
