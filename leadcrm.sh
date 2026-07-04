#!/bin/bash

# ============================================================
# LEAD CRM - BASH v2.0
# Полноценная система управления лидами, менеджерами и розыгрышами
# ============================================================

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

DATA_DIR="${HOME}/.leadcrm"
DB_FILE="${DATA_DIR}/leads.db"
CONFIG_FILE="${DATA_DIR}/config.cfg"
LOG_FILE="${DATA_DIR}/leadcrm.log"
SESSION_FILE="${DATA_DIR}/session.txt"

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
NC='\033[0m'

# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================

init() {
    mkdir -p "$DATA_DIR"
    
    if [ ! -f "$DB_FILE" ]; then
        echo -e "${BLUE}📦 Создание базы данных...${NC}"
        init_db
    fi
    
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${BLUE}⚙️  Создание конфигурации...${NC}"
        init_config
    fi
    
    source "$CONFIG_FILE"
    log "INFO" "Lead CRM v2.0 запущен"
}

init_db() {
    sqlite3 "$DB_FILE" <<'EOF'
-- ============================================================
-- Таблицы
-- ============================================================

-- Менеджеры
CREATE TABLE IF NOT EXISTS managers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT DEFAULT 'manager',
    is_active INTEGER DEFAULT 1,
    balance REAL DEFAULT 0,
    total_earned REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Лиды
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vk_id TEXT UNIQUE NOT NULL,
    vk_url TEXT NOT NULL,
    name TEXT DEFAULT '',
    source TEXT DEFAULT '',
    status TEXT DEFAULT 'new',
    manager_id INTEGER,
    notes TEXT DEFAULT '',
    balance REAL DEFAULT 0,
    found_at TEXT DEFAULT (datetime('now')),
    participation_count INTEGER DEFAULT 0,
    last_contact TEXT,
    FOREIGN KEY (manager_id) REFERENCES managers(id)
);

-- Статусы лидов
CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    changed_at TEXT DEFAULT (datetime('now')),
    manager_id INTEGER,
    comment TEXT,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

-- Скрипты
CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    body TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Участия в розыгрышах
CREATE TABLE IF NOT EXISTS participations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    manager_id INTEGER NOT NULL,
    round_date TEXT NOT NULL,
    round_slot TEXT NOT NULL,
    screenshot TEXT,
    status TEXT DEFAULT 'pending',
    comment TEXT,
    reviewed_by INTEGER,
    reviewed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(lead_id, round_date, round_slot),
    FOREIGN KEY (lead_id) REFERENCES leads(id),
    FOREIGN KEY (manager_id) REFERENCES managers(id)
);

-- Заявки на вывод
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    status TEXT DEFAULT 'pending',
    comment TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT,
    FOREIGN KEY (manager_id) REFERENCES managers(id)
);

-- Балансовая книга (все транзакции)
CREATE TABLE IF NOT EXISTS balance_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id INTEGER NOT NULL,
    lead_id INTEGER,
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    reference_id INTEGER,
    comment TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (manager_id) REFERENCES managers(id)
);

-- Журнал действий
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Уведомления
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (manager_id) REFERENCES managers(id)
);

-- ============================================================
-- Индексы
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_leads_manager ON leads(manager_id);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_participations_lead ON participations(lead_id);
CREATE INDEX IF NOT EXISTS idx_participations_status ON participations(status);
CREATE INDEX IF NOT EXISTS idx_withdrawals_manager ON withdrawals(manager_id);
CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status);
CREATE INDEX IF NOT EXISTS idx_notifications_manager ON notifications(manager_id);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(is_read);

-- ============================================================
-- Создание админа
-- ============================================================

INSERT OR IGNORE INTO managers (login, password, name, role) 
VALUES ('admin', 'admin123', 'Администратор', 'admin');

EOF
    echo -e "${GREEN}✅ База данных создана${NC}"
}

init_config() {
    cat > "$CONFIG_FILE" <<EOF
# Lead CRM Configuration
ADMIN_LOGIN="admin"
ADMIN_PASSWORD="admin123"
COMMISSION_PCT=20
MIN_WITHDRAWAL=30
APP_NAME="Lead CRM"
PENALTY_AMOUNT=1
EOF
}

# ============================================================
# УТИЛИТЫ
# ============================================================

log() {
    local level="$1"
    local message="$2"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $message" >> "$LOG_FILE"
}

db_query() {
    sqlite3 "$DB_FILE" "$1"
}

db_query_table() {
    sqlite3 -table "$DB_FILE" "$1"
}

db_query_json() {
    sqlite3 "$DB_FILE" -json "$1"
}

print_header() {
    clear
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════════╗"
    echo "║                    LEAD CRM - BASH v2.0                          ║"
    echo "╠═══════════════════════════════════════════════════════════════════╣"
    echo "║  📊 Управление лидами | 👥 Менеджеры | 🎁 Розыгрыши | 💰 Выводы ║"
    echo "╚═══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_menu() {
    echo -e "${YELLOW}📋 ГЛАВНОЕ МЕНЮ${NC}"
    echo ""
    echo "  ${GREEN}1${NC}) 📋 Лиды"
    echo "  ${GREEN}2${NC}) 👥 Менеджеры"
    echo "  ${GREEN}3${NC}) 🎁 Розыгрыши"
    echo "  ${GREEN}4${NC}) 💰 Выводы"
    echo "  ${GREEN}5${NC}) 📝 Скрипты"
    echo "  ${GREEN}6${NC}) 📊 Рейтинг"
    echo "  ${GREEN}7${NC}) 📜 Журнал"
    echo "  ${GREEN}8${NC}) 🔔 Уведомления"
    echo "  ${GREEN}9${NC}) ⚙️  Настройки"
    echo "  ${GREEN}0${NC}) 🚪 Выход"
    echo ""
}

# ============================================================
# АВТОРИЗАЦИЯ
# ============================================================

login() {
    clear
    print_header
    echo -e "${BLUE}🔐 ВХОД В СИСТЕМУ${NC}"
    echo ""
    
    read -p "Логин: " login
    read -sp "Пароль: " password
    echo ""
    
    local result=$(db_query "SELECT id, name, role, balance FROM managers WHERE login='$login' AND password='$password' AND is_active=1")
    
    if [ -n "$result" ]; then
        CURRENT_USER_ID=$(echo "$result" | cut -d'|' -f1)
        CURRENT_USER_NAME=$(echo "$result" | cut -d'|' -f2)
        CURRENT_USER_ROLE=$(echo "$result" | cut -d'|' -f3)
        CURRENT_USER_BALANCE=$(echo "$result" | cut -d'|' -f4)
        
        echo "$CURRENT_USER_ID|$CURRENT_USER_NAME|$CURRENT_USER_ROLE|$CURRENT_USER_BALANCE" > "$SESSION_FILE"
        
        echo -e "${GREEN}✅ Добро пожаловать, $CURRENT_USER_NAME!${NC}"
        log "INFO" "Пользователь $CURRENT_USER_NAME вошел в систему"
        sleep 1
        return 0
    else
        echo -e "${RED}❌ Неверный логин или пароль${NC}"
        log "WARN" "Неудачная попытка входа: $login"
        sleep 2
        return 1
    fi
}

check_session() {
    if [ ! -f "$SESSION_FILE" ]; then
        echo -e "${RED}❌ Вы не авторизованы${NC}"
        sleep 1
        return 1
    fi
    
    IFS='|' read -r CURRENT_USER_ID CURRENT_USER_NAME CURRENT_USER_ROLE CURRENT_USER_BALANCE < "$SESSION_FILE"
    
    # Проверка что пользователь существует и активен
    local exists=$(db_query "SELECT id FROM managers WHERE id=$CURRENT_USER_ID AND is_active=1")
    if [ -z "$exists" ]; then
        echo -e "${RED}❌ Сессия недействительна${NC}"
        rm -f "$SESSION_FILE"
        sleep 1
        return 1
    fi
    
    return 0
}

logout() {
    rm -f "$SESSION_FILE"
    echo -e "${GREEN}👋 Вы вышли из системы${NC}"
    log "INFO" "Пользователь $CURRENT_USER_NAME вышел из системы"
    sleep 1
}

# ============================================================
# УПРАВЛЕНИЕ ЛИДАМИ
# ============================================================

leads_menu() {
    while true; do
        clear
        print_header
        echo -e "${YELLOW}📋 УПРАВЛЕНИЕ ЛИДАМИ${NC}"
        echo -e "${BLUE}👤 $CURRENT_USER_NAME | Баланс: ${GREEN}${CURRENT_USER_BALANCE:-0}G${NC}"
        echo ""
        echo "  ${GREEN}1${NC}) 📋 Список лидов"
        echo "  ${GREEN}2${NC}) ➕ Добавить лида"
        echo "  ${GREEN}3${NC}) 🔍 Поиск лида"
        echo "  ${GREEN}4${NC}) 📊 Статусы"
        echo "  ${GREEN}5${NC}) ✏️  Изменить статус"
        echo "  ${GREEN}6${NC}) 📝 Добавить заметку"
        echo "  ${GREEN}7${NC}) ↩️  Назад"
        echo ""
        read -p "Выберите действие: " choice
        
        case $choice in
            1) leads_list ;;
            2) leads_add ;;
            3) leads_search ;;
            4) leads_statuses ;;
            5) leads_change_status ;;
            6) leads_add_note ;;
            7) return ;;
            *) echo -e "${RED}Неверный выбор${NC}" ;;
        esac
    done
}

leads_list() {
    clear
    print_header
    echo -e "${YELLOW}📋 СПИСОК ЛИДОВ${NC}"
    echo ""
    
    if [ "$CURRENT_USER_ROLE" = "admin" ]; then
        db_query_table "SELECT id, name, vk_id, status, balance, manager_id FROM leads ORDER BY id DESC LIMIT 50"
    else
        db_query_table "SELECT id, name, vk_id, status, balance FROM leads WHERE manager_id=$CURRENT_USER_ID ORDER BY id DESC LIMIT 50"
    fi
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

leads_add() {
    clear
    print_header
    echo -e "${YELLOW}➕ ДОБАВЛЕНИЕ ЛИДА${NC}"
    echo ""
    
    read -p "Ссылка VK (vk.com/id123): " vk_url
    read -p "Имя (опционально): " name
    read -p "Группа-источник: " source
    
    if [ -z "$vk_url" ]; then
        echo -e "${RED}❌ Ссылка обязательна${NC}"
        sleep 1
        return
    fi
    
    # Нормализация VK ID
    vk_id=$(echo "$vk_url" | sed 's|https\?://||g' | sed 's|vk.com/||g' | sed 's|/||g')
    
    # Проверка на дубликат
    existing=$(db_query "SELECT id, manager_id FROM leads WHERE vk_id='$vk_id'")
    
    if [ -n "$existing" ]; then
        owner_id=$(echo "$existing" | cut -d'|' -f2)
        owner_name=$(db_query "SELECT name FROM managers WHERE id=$owner_id")
        echo -e "${YELLOW}⚠️  Лид уже существует! Ведет: ${owner_name:-неизвестно}${NC}"
        sleep 2
        return
    fi
    
    manager_id=$CURRENT_USER_ID
    if [ "$CURRENT_USER_ROLE" = "admin" ]; then
        read -p "Назначить менеджеру (ID, 0 - себе): " manager_id
        [ "$manager_id" = "0" ] && manager_id=$CURRENT_USER_ID
    fi
    
    db_query "INSERT INTO leads (vk_id, vk_url, name, source, manager_id) 
              VALUES ('$vk_id', '$vk_url', '$name', '$source', $manager_id)"
    
    local lead_id=$(db_query "SELECT last_insert_rowid()")
    
    # Добавляем в историю статусов
    db_query "INSERT INTO status_history (lead_id, status, manager_id) VALUES ($lead_id, 'new', $manager_id)"
    
    # Логируем действие
    log "INFO" "Добавлен лид: $vk_url ($CURRENT_USER_NAME)"
    
    echo -e "${GREEN}✅ Лид добавлен!${NC}"
    sleep 1
}

leads_search() {
    clear
    print_header
    echo -e "${YELLOW}🔍 ПОИСК ЛИДА${NC}"
    echo ""
    
    read -p "Поиск (имя или VK ID): " query
    
    if [ -z "$query" ]; then
        echo -e "${RED}❌ Введите запрос${NC}"
        sleep 1
        return
    fi
    
    echo -e "${BLUE}Результаты поиска:${NC}"
    db_query_table "SELECT id, name, vk_id, status, balance FROM leads 
                     WHERE name LIKE '%$query%' OR vk_id LIKE '%$query%'"
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

leads_statuses() {
    clear
    print_header
    echo -e "${YELLOW}📊 СТАТУСЫ ЛИДОВ${NC}"
    echo ""
    
    if [ "$CURRENT_USER_ROLE" = "admin" ]; then
        local total=$(db_query "SELECT COUNT(*) FROM leads")
        local new=$(db_query "SELECT COUNT(*) FROM leads WHERE status='new'")
        local contacted=$(db_query "SELECT COUNT(*) FROM leads WHERE status='contacted'")
        local replied=$(db_query "SELECT COUNT(*) FROM leads WHERE status='replied'")
        local joined=$(db_query "SELECT COUNT(*) FROM leads WHERE status='joined_channel'")
        local participated=$(db_query "SELECT COUNT(*) FROM leads WHERE status='participated'")
        local returning=$(db_query "SELECT COUNT(*) FROM leads WHERE status='returning'")
        local declined=$(db_query "SELECT COUNT(*) FROM leads WHERE status='declined'")
    else
        local total=$(db_query "SELECT COUNT(*) FROM leads WHERE manager_id=$CURRENT_USER_ID")
        local new=$(db_query "SELECT COUNT(*) FROM leads WHERE manager_id=$CURRENT_USER_ID AND status='new'")
        local contacted=$(db_query "SELECT COUNT(*) FROM leads WHERE manager_id=$CURRENT_USER_ID AND status='contacted'")
        local replied=$(db_query "SELECT COUNT(*) FROM leads WHERE manager_id=$CURRENT_USER_ID AND status='replied'")
        local joined=$(db_query "SELECT COUNT(*) FROM leads WHERE manager_id=$CURRENT_USER_ID AND status='joined_channel'")
        local participated=$(db_query "SELECT COUNT(*) FROM leads WHERE manager_id=$CURRENT_USER_ID AND status='participated'")
        local returning=$(db_query "SELECT COUNT(*) FROM leads WHERE manager_id=$CURRENT_USER_ID AND status='returning'")
        local declined=$(db_query "SELECT COUNT(*) FROM leads WHERE manager_id=$CURRENT_USER_ID AND status='declined'")
    fi
    
    echo -e "${BLUE}📊 Статистика по лидам:${NC}"
    echo ""
    echo -e "  ${WHITE}Всего:${NC} $total"
    echo -e "  ${YELLOW}Новые:${NC} $new"
    echo -e "  ${BLUE}Написали:${NC} $contacted"
    echo -e "  ${GREEN}Ответили:${NC} $replied"
    echo -e "  ${CYAN}Вступили в канал:${NC} $joined"
    echo -e "  ${MAGENTA}Участвовали:${NC} $participated"
    echo -e "  ${GREEN}Возвращаются:${NC} $returning"
    echo -e "  ${RED}Отказались:${NC} $declined"
    
    # Расчет конверсии
    if [ $total -gt 0 ]; then
        local conv=$(echo "scale=1; ($returning * 100) / $total" | bc)
        echo -e "${BLUE}📈 Общая конверсия:${NC} ${conv}%"
    fi
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

leads_change_status() {
    clear
    print_header
    echo -e "${YELLOW}✏️  ИЗМЕНЕНИЕ СТАТУСА${NC}"
    echo ""
    
    read -p "ID лида: " lead_id
    
    # Проверка доступа
    local check=$(db_query "SELECT id FROM leads WHERE id=$lead_id AND (manager_id=$CURRENT_USER_ID OR 1=$CURRENT_USER_ROLE='admin')")
    if [ -z "$check" ]; then
        echo -e "${RED}❌ Лид не найден или не ваш${NC}"
        sleep 1
        return
    fi
    
    echo ""
    echo -e "${BLUE}Доступные статусы:${NC}"
    echo "  1) new (Новый)"
    echo "  2) contacted (Написали)"
    echo "  3) replied (Ответил)"
    echo "  4) joined_channel (Вступил в канал)"
    echo "  5) participated (Участвовал)"
    echo "  6) returning (Возвращается)"
    echo "  7) declined (Отказался)"
    echo ""
    
    read -p "Выберите статус (1-7): " status_choice
    
    case $status_choice in
        1) new_status="new" ;;
        2) new_status="contacted" ;;
        3) new_status="replied" ;;
        4) new_status="joined_channel" ;;
        5) new_status="participated" ;;
        6) new_status="returning" ;;
        7) new_status="declined" ;;
        *) echo -e "${RED}Неверный выбор${NC}"; sleep 1; return ;;
    esac
    
    read -p "Комментарий (опционально): " comment
    
    # Сохраняем старый статус
    local old_status=$(db_query "SELECT status FROM leads WHERE id=$lead_id")
    
    # Обновляем статус
    db_query "UPDATE leads SET status='$new_status', last_contact=datetime('now') WHERE id=$lead_id"
    
    # Добавляем в историю
    db_query "INSERT INTO status_history (lead_id, status, manager_id, comment) 
              VALUES ($lead_id, '$new_status', $CURRENT_USER_ID, '$comment')"
    
    log "INFO" "Изменен статус лида $lead_id: $old_status -> $new_status ($CURRENT_USER_NAME)"
    echo -e "${GREEN}✅ Статус обновлен!${NC}"
    sleep 1
}

leads_add_note() {
    clear
    print_header
    echo -e "${YELLOW}📝 ДОБАВЛЕНИЕ ЗАМЕТКИ${NC}"
    echo ""
    
    read -p "ID лида: " lead_id
    
    local check=$(db_query "SELECT id FROM leads WHERE id=$lead_id AND (manager_id=$CURRENT_USER_ID OR '$CURRENT_USER_ROLE'='admin')")
    if [ -z "$check" ]; then
        echo -e "${RED}❌ Лид не найден или не ваш${NC}"
        sleep 1
        return
    fi
    
    read -p "Заметка: " note
    
    local current_notes=$(db_query "SELECT notes FROM leads WHERE id=$lead_id")
    local new_notes="${current_notes}\n[$(date '+%Y-%m-%d %H:%M')] $CURRENT_USER_NAME: $note"
    
    db_query "UPDATE leads SET notes='$new_notes' WHERE id=$lead_id"
    
    echo -e "${GREEN}✅ Заметка добавлена!${NC}"
    sleep 1
}

# ============================================================
# УПРАВЛЕНИЕ МЕНЕДЖЕРАМИ
# ============================================================

managers_menu() {
    if [ "$CURRENT_USER_ROLE" != "admin" ]; then
        echo -e "${RED}❌ Доступ запрещен (только админ)${NC}"
        sleep 1
        return
    fi
    
    while true; do
        clear
        print_header
        echo -e "${YELLOW}👥 УПРАВЛЕНИЕ МЕНЕДЖЕРАМИ${NC}"
        echo ""
        echo "  ${GREEN}1${NC}) 📋 Список менеджеров"
        echo "  ${GREEN}2${NC}) ➕ Добавить менеджера"
        echo "  ${GREEN}3${NC}) 🔄 Редактировать"
        echo "  ${GREEN}4${NC}) 🔄 Вкл/Выкл"
        echo "  ${GREEN}5${NC}) 💰 Корректировка баланса"
        echo "  ${GREEN}6${NC}) ↩️  Назад"
        echo ""
        read -p "Выберите действие: " choice
        
        case $choice in
            1) managers_list ;;
            2) managers_add ;;
            3) managers_edit ;;
            4) managers_toggle ;;
            5) managers_adjust_balance ;;
            6) return ;;
            *) echo -e "${RED}Неверный выбор${NC}" ;;
        esac
    done
}

managers_list() {
    clear
    print_header
    echo -e "${YELLOW}📋 СПИСОК МЕНЕДЖЕРОВ${NC}"
    echo ""
    
    db_query_table "SELECT id, name, login, role, is_active, balance, total_earned FROM managers ORDER BY id"
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

managers_add() {
    clear
    print_header
    echo -e "${YELLOW}➕ ДОБАВЛЕНИЕ МЕНЕДЖЕРА${NC}"
    echo ""
    
    read -p "Имя: " name
    read -p "Логин: " login
    read -sp "Пароль: " password
    echo ""
    
    if [ -z "$name" ] || [ -z "$login" ] || [ -z "$password" ]; then
        echo -e "${RED}❌ Все поля обязательны${NC}"
        sleep 1
        return
    fi
    
    # Проверка уникальности логина
    local exists=$(db_query "SELECT id FROM managers WHERE login='$login'")
    if [ -n "$exists" ]; then
        echo -e "${RED}❌ Логин уже занят${NC}"
        sleep 1
        return
    fi
    
    db_query "INSERT INTO managers (login, password, name) VALUES ('$login', '$password', '$name')"
    
    echo -e "${GREEN}✅ Менеджер добавлен!${NC}"
    log "INFO" "Добавлен менеджер: $name ($login)"
    sleep 1
}

managers_edit() {
    clear
    print_header
    echo -e "${YELLOW}🔄 РЕДАКТИРОВАНИЕ МЕНЕДЖЕРА${NC}"
    echo ""
    
    managers_list
    echo ""
    read -p "ID менеджера: " id
    
    local manager=$(db_query "SELECT * FROM managers WHERE id=$id")
    if [ -z "$manager" ]; then
        echo -e "${RED}❌ Менеджер не найден${NC}"
        sleep 1
        return
    fi
    
    local current_name=$(echo "$manager" | cut -d'|' -f3)
    local current_login=$(echo "$manager" | cut -d'|' -f2)
    
    read -p "Новое имя (текущее: $current_name): " name
    read -p "Новый логин (текущий: $current_login): " login
    read -sp "Новый пароль (оставьте пустым): " password
    echo ""
    
    [ -n "$name" ] && db_query "UPDATE managers SET name='$name' WHERE id=$id"
    [ -n "$login" ] && db_query "UPDATE managers SET login='$login' WHERE id=$id"
    [ -n "$password" ] && db_query "UPDATE managers SET password='$password' WHERE id=$id"
    
    echo -e "${GREEN}✅ Обновлено!${NC}"
    log "INFO" "Обновлен менеджер ID $id"
    sleep 1
}

managers_toggle() {
    clear
    print_header
    echo -e "${YELLOW}🔄 ВКЛ/ВЫКЛ МЕНЕДЖЕРА${NC}"
    echo ""
    
    managers_list
    echo ""
    read -p "ID менеджера: " id
    
    local current=$(db_query "SELECT is_active FROM managers WHERE id=$id")
    local new=$((1 - current))
    
    db_query "UPDATE managers SET is_active=$new WHERE id=$id"
    
    echo -e "${GREEN}✅ Статус изменен${NC}"
    log "INFO" "Изменен статус менеджера ID $id на $new"
    sleep 1
}

managers_adjust_balance() {
    clear
    print_header
    echo -e "${YELLOW}💰 КОРРЕКТИРОВКА БАЛАНСА${NC}"
    echo ""
    
    managers_list
    echo ""
    read -p "ID менеджера: " id
    read -p "Сумма (например +10 или -5): " amount
    read -p "Причина: " reason
    
    local current_balance=$(db_query "SELECT balance FROM managers WHERE id=$id")
    local new_balance=$(echo "$current_balance + $amount" | bc)
    
    db_query "UPDATE managers SET balance=$new_balance WHERE id=$id"
    db_query "INSERT INTO balance_ledger (manager_id, amount, reason, comment) 
              VALUES ($id, $amount, 'admin_adjustment', '$reason')"
    
    # Уведомление менеджера
    db_query "INSERT INTO notifications (manager_id, message) 
              VALUES ($id, 'Администратор изменил ваш баланс на $amount G. Причина: $reason')"
    
    echo -e "${GREEN}✅ Баланс обновлен!${NC}"
    log "INFO" "Корректировка баланса менеджера $id: $amount ($reason)"
    sleep 1
}

# ============================================================
# РОЗЫГРЫШИ
# ============================================================

raffles_menu() {
    while true; do
        clear
        print_header
        echo -e "${YELLOW}🎁 РОЗЫГРЫШИ${NC}"
        echo -e "${BLUE}👤 $CURRENT_USER_NAME | Баланс: ${GREEN}${CURRENT_USER_BALANCE:-0}G${NC}"
        echo ""
        echo "  ${GREEN}1${NC}) 📋 Текущий раунд"
        echo "  ${GREEN}2${NC}) ✏️  Отметить участие (с отправкой скриншота)"
        echo "  ${GREEN}3${NC}) 📊 Мои заявки"
        echo "  ${GREEN}4${NC}) ✅ Проверить заявки (админ)"
        echo "  ${GREEN}5${NC}) ↩️  Назад"
        echo ""
        read -p "Выберите действие: " choice
        
        case $choice in
            1) raffle_current ;;
            2) raffle_participate ;;
            3) raffle_my_submissions ;;
            4) raffle_review ;;
            5) return ;;
            *) echo -e "${RED}Неверный выбор${NC}" ;;
        esac
    done
}

raffle_current() {
    clear
    print_header
    echo -e "${YELLOW}📋 ТЕКУЩИЙ РАУНД${NC}"
    echo ""
    
    today=$(date '+%Y-%m-%d')
    slots=("12:00" "18:00" "00:00")
    
    echo -e "${BLUE}Сегодня: $today${NC}"
    echo ""
    
    for slot in "${slots[@]}"; do
        local count=$(db_query "SELECT COUNT(*) FROM participations WHERE round_date='$today' AND round_slot='$slot' AND status='approved'")
        local pending=$(db_query "SELECT COUNT(*) FROM participations WHERE round_date='$today' AND round_slot='$slot' AND status='pending'")
        echo -e "  ${YELLOW}Слот $slot:${NC} $count участников (ожидают: $pending)"
    done
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

raffle_participate() {
    clear
    print_header
    echo -e "${YELLOW}✏️  ОТМЕТИТЬ УЧАСТИЕ${NC}"
    echo ""
    
    echo -e "${RED}⚠️  ВНИМАНИЕ:${NC}"
    echo -e "${YELLOW}Если вы ошибетесь и укажете не того лида, заявка будет отклонена,"
    echo -e "и с вашего баланса спишется ${PENALTY_AMOUNT} G за ошибку!${NC}"
    echo ""
    
    read -p "VK ID лида: " vk_id
    read -p "Слот (12:00/18:00/00:00): " slot
    round_date=$(date '+%Y-%m-%d')
    
    # Находим лида
    local lead=$(db_query "SELECT id, name, manager_id FROM leads WHERE vk_id='$vk_id'")
    
    if [ -z "$lead" ]; then
        echo -e "${RED}❌ Лид не найден${NC}"
        sleep 2
        return
    fi
    
    local lead_id=$(echo "$lead" | cut -d'|' -f1)
    local lead_name=$(echo "$lead" | cut -d'|' -f2)
    local lead_manager=$(echo "$lead" | cut -d'|' -f3)
    
    # Проверка что лид принадлежит менеджеру
    if [ "$CURRENT_USER_ROLE" != "admin" ] && [ "$lead_manager" != "$CURRENT_USER_ID" ]; then
        echo -e "${RED}❌ Этот лид не ваш!${NC}"
        sleep 2
        return
    fi
    
    # Проверка на дубликат
    local exists=$(db_query "SELECT id FROM participations WHERE lead_id=$lead_id AND round_date='$round_date' AND round_slot='$slot'")
    
    if [ -n "$exists" ]; then
        echo -e "${YELLOW}⚠️  Участие уже отмечено${NC}"
        sleep 2
        return
    fi
    
    echo -e "${BLUE}📸 Прикрепите скриншот с подтверждением участия:${NC}"
    echo -e "${YELLOW}Введите путь к файлу (например: /path/to/screenshot.jpg)${NC}"
    echo -e "${MAGENTA}Или оставьте пустым для пропуска скриншота${NC}"
    read -p "Путь к скриншоту: " screenshot_path
    
    local screenshot=""
    if [ -n "$screenshot_path" ] && [ -f "$screenshot_path" ]; then
        # Копируем скриншот в папку данных
        local ext="${screenshot_path##*.}"
        local new_name="screenshot_${lead_id}_$(date +%s).${ext}"
        cp "$screenshot_path" "$DATA_DIR/$new_name"
        screenshot="$new_name"
        echo -e "${GREEN}✅ Скриншот загружен${NC}"
    else
        echo -e "${YELLOW}⚠️  Скриншот не прикреплен${NC}"
        echo -e "${RED}❌ Без скриншота заявка не будет принята!${NC}"
        sleep 2
        return
    fi
    
    # Создаем заявку
    db_query "INSERT INTO participations (lead_id, manager_id, round_date, round_slot, screenshot, status) 
              VALUES ($lead_id, $CURRENT_USER_ID, '$round_date', '$slot', '$screenshot', 'pending')"
    
    # Уведомление админам
    local admins=$(db_query "SELECT id FROM managers WHERE role='admin'")
    for admin_id in $admins; do
        db_query "INSERT INTO notifications (manager_id, message) 
                  VALUES ($admin_id, 'Новая заявка на участие от $CURRENT_USER_NAME для лида $lead_name')"
    done
    
    echo -e "${GREEN}✅ Заявка отправлена на проверку!${NC}"
    log "INFO" "Заявка на участие: $lead_name ($CURRENT_USER_NAME)"
    sleep 2
}

raffle_my_submissions() {
    clear
    print_header
    echo -e "${YELLOW}📊 МОИ ЗАЯВКИ${NC}"
    echo ""
    
    db_query_table "SELECT id, lead_id, round_date, round_slot, status, created_at 
                     FROM participations WHERE manager_id=$CURRENT_USER_ID 
                     ORDER BY id DESC LIMIT 20"
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

raffle_review() {
    if [ "$CURRENT_USER_ROLE" != "admin" ]; then
        echo -e "${RED}❌ Доступ запрещен (только админ)${NC}"
        sleep 1
        return
    fi
    
    clear
    print_header
    echo -e "${YELLOW}✅ ПРОВЕРКА ЗАЯВОК${NC}"
    echo ""
    
    local pending=$(db_query "SELECT COUNT(*) FROM participations WHERE status='pending'")
    
    if [ "$pending" -eq 0 ]; then
        echo -e "${GREEN}✅ Нет заявок на проверку${NC}"
        sleep 1
        return
    fi
    
    echo -e "${BLUE}Заявок на проверку: $pending${NC}"
    echo ""
    
    db_query_table "SELECT p.id, l.name, l.vk_id, m.name as manager, p.round_date, p.round_slot, p.screenshot 
                     FROM participations p 
                     JOIN leads l ON l.id = p.lead_id 
                     JOIN managers m ON m.id = p.manager_id 
                     WHERE p.status='pending'"
    
    echo ""
    read -p "ID заявки для проверки (0 - выход): " sub_id
    
    if [ "$sub_id" = "0" ] || [ -z "$sub_id" ]; then
        return
    fi
    
    local sub=$(db_query "SELECT * FROM participations WHERE id=$sub_id AND status='pending'")
    if [ -z "$sub" ]; then
        echo -e "${RED}❌ Заявка не найдена или уже проверена${NC}"
        sleep 1
        return
    fi
    
    local lead_id=$(echo "$sub" | cut -d'|' -f2)
    local manager_id=$(echo "$sub" | cut -d'|' -f3)
    local screenshot=$(echo "$sub" | cut -d'|' -f6)
    
    echo ""
    echo -e "${BLUE}📸 Скриншот:${NC}"
    if [ -n "$screenshot" ] && [ -f "$DATA_DIR/$screenshot" ]; then
        echo -e "${YELLOW}Файл: $DATA_DIR/$screenshot${NC}"
        # Попытка показать картинку (если есть инструменты)
        if command -v display &> /dev/null; then
            display "$DATA_DIR/$screenshot" &
        elif command -v open &> /dev/null; then
            open "$DATA_DIR/$screenshot" &
        fi
    else
        echo -e "${RED}❌ Скриншот не найден${NC}"
    fi
    
    echo ""
    echo -e "${GREEN}1${NC}) ✅ Одобрить (+10G лиду и менеджеру)"
    echo -e "${RED}2${NC}) ❌ Отклонить (штраф ${PENALTY_AMOUNT}G с менеджера)"
    echo -e "${YELLOW}3${NC}) ↪️  Пропустить"
    echo ""
    read -p "Выберите действие: " decision
    
    local lead_name=$(db_query "SELECT name FROM leads WHERE id=$lead_id")
    
    case $decision in
        1)
            # Одобрение
            db_query "UPDATE participations SET status='approved', reviewed_by=$CURRENT_USER_ID, reviewed_at=datetime('now') WHERE id=$sub_id"
            
            # Начисление лиду
            db_query "UPDATE leads SET balance = balance + 10, participation_count = participation_count + 1 WHERE id=$lead_id"
            db_query "INSERT INTO balance_ledger (manager_id, lead_id, amount, reason, reference_id) 
                      VALUES ($CURRENT_USER_ID, $lead_id, 10, 'submission_approved', $sub_id)"
            
            # Начисление менеджеру
            db_query "UPDATE managers SET balance = balance + 10, total_earned = total_earned + 10 WHERE id=$manager_id"
            db_query "INSERT INTO balance_ledger (manager_id, amount, reason, reference_id) 
                      VALUES ($manager_id, 10, 'submission_approved', $sub_id)"
            
            # Обновление статуса лида
            local count=$(db_query "SELECT participation_count FROM leads WHERE id=$lead_id")
            local new_status="participated"
            if [ "$count" -ge 2 ]; then
                new_status="returning"
            fi
            db_query "UPDATE leads SET status='$new_status' WHERE id=$lead_id"
            
            # Уведомление менеджеру
            db_query "INSERT INTO notifications (manager_id, message) 
                      VALUES ($manager_id, '✅ Ваша заявка для $lead_name одобрена! Получено +10G')"
            
            echo -e "${GREEN}✅ Заявка одобрена!${NC}"
            log "INFO" "Одобрена заявка #$sub_id ($CURRENT_USER_NAME)"
            ;;
        2)
            # Отклонение со штрафом
            db_query "UPDATE participations SET status='rejected', reviewed_by=$CURRENT_USER_ID, reviewed_at=datetime('now'), comment='Ошибка в заявке' WHERE id=$sub_id"
            
            # Штраф менеджеру
            db_query "UPDATE managers SET balance = balance - $PENALTY_AMOUNT WHERE id=$manager_id"
            db_query "INSERT INTO balance_ledger (manager_id, amount, reason, reference_id, comment) 
                      VALUES ($manager_id, -$PENALTY_AMOUNT, 'submission_penalty', $sub_id, 'Штраф за ошибку в заявке')"
            
            # Уведомление менеджеру
            db_query "INSERT INTO notifications (manager_id, message) 
                      VALUES ($manager_id, "❌ Ваша заявка для $lead_name отклонена! С баланса списано $PENALTY_AMOUNT G за ошибку.")"
            
            echo -e "${RED}❌ Заявка отклонена, списано $PENALTY_AMOUNT G${NC}"
            log "INFO" "Отклонена заявка #$sub_id ($CURRENT_USER_NAME)"
            ;;
        3)
            echo -e "${YELLOW}↪️  Пропущено${NC}"
            ;;
        *)
            echo -e "${RED}Неверный выбор${NC}"
            ;;
    esac
    
    sleep 2
}

# ============================================================
# ВЫВОДЫ
# ============================================================

withdrawals_menu() {
    while true; do
        clear
        print_header
        echo -e "${YELLOW}💰 ВЫВОДЫ${NC}"
        echo -e "${BLUE}👤 $CURRENT_USER_NAME | Баланс: ${GREEN}${CURRENT_USER_BALANCE:-0}G${NC}"
        echo ""
        echo "  ${GREEN}1${NC}) 📋 Мои выводы"
        echo "  ${GREEN}2${NC}) ➕ Запросить вывод"
        echo "  ${GREEN}3${NC}) ✅ Проверить выводы (админ)"
        echo "  ${GREEN}4${NC}) ↩️  Назад"
        echo ""
        read -p "Выберите действие: " choice
        
        case $choice in
            1) withdrawals_list ;;
            2) withdrawals_request ;;
            3) withdrawals_review ;;
            4) return ;;
            *) echo -e "${RED}Неверный выбор${NC}" ;;
        esac
    done
}

withdrawals_list() {
    clear
    print_header
    echo -e "${YELLOW}📋 МОИ ВЫВОДЫ${NC}"
    echo ""
    
    db_query_table "SELECT id, amount, status, created_at FROM withdrawals 
                     WHERE manager_id=$CURRENT_USER_ID ORDER BY id DESC"
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

withdrawals_request() {
    clear
    print_header
    echo -e "${YELLOW}➕ ЗАПРОС ВЫВОДА${NC}"
    echo ""
    
    local balance=$(db_query "SELECT balance FROM managers WHERE id=$CURRENT_USER_ID")
    
    echo -e "${BLUE}Ваш баланс: ${GREEN}${balance}G${NC}"
    echo -e "${BLUE}Минимальная сумма вывода: ${YELLOW}${MIN_WITHDRAWAL}G${NC}"
    echo ""
    
    if [ "$(echo "$balance < $MIN_WITHDRAWAL" | bc)" -eq 1 ]; then
        echo -e "${RED}❌ Недостаточно средств для вывода${NC}"
        sleep 2
        return
    fi
    
    read -p "Сумма вывода: " amount
    
    if [ -z "$amount" ] || [ "$(echo "$amount < $MIN_WITHDRAWAL" | bc)" -eq 1 ]; then
        echo -e "${RED}❌ Сумма должна быть не меньше ${MIN_WITHDRAWAL}G${NC}"
        sleep 2
        return
    fi
    
    if [ "$(echo "$amount > $balance" | bc)" -eq 1 ]; then
        echo -e "${RED}❌ Недостаточно средств${NC}"
        sleep 2
        return
    fi
    
    # Создаем заявку на вывод
    db_query "INSERT INTO withdrawals (manager_id, amount, status) VALUES ($CURRENT_USER_ID, $amount, 'pending')"
    local wid=$(db_query "SELECT last_insert_rowid()")
    
    # Блокируем средства
    local new_balance=$(echo "$balance - $amount" | bc)
    db_query "UPDATE managers SET balance=$new_balance WHERE id=$CURRENT_USER_ID"
    db_query "INSERT INTO balance_ledger (manager_id, amount, reason, reference_id) 
              VALUES ($CURRENT_USER_ID, -$amount, 'withdrawal_request', $wid)"
    
    # Уведомление админам
    local admins=$(db_query "SELECT id FROM managers WHERE role='admin'")
    for admin_id in $admins; do
        db_query "INSERT INTO notifications (manager_id, message) 
                  VALUES ($admin_id, '💰 Заявка на вывод от $CURRENT_USER_NAME на сумму ${amount}G')"
    done
    
    # Обновляем баланс в сессии
    CURRENT_USER_BALANCE=$new_balance
    
    echo -e "${GREEN}✅ Заявка на вывод отправлена!${NC}"
    log "INFO" "Заявка на вывод: $CURRENT_USER_NAME на $amount G"
    sleep 2
}

withdrawals_review() {
    if [ "$CURRENT_USER_ROLE" != "admin" ]; then
        echo -e "${RED}❌ Доступ запрещен (только админ)${NC}"
        sleep 1
        return
    fi
    
    clear
    print_header
    echo -e "${YELLOW}✅ ПРОВЕРКА ВЫВОДОВ${NC}"
    echo ""
    
    local pending=$(db_query "SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    
    if [ "$pending" -eq 0 ]; then
        echo -e "${GREEN}✅ Нет заявок на вывод${NC}"
        sleep 1
        return
    fi
    
    echo -e "${BLUE}Заявок на вывод: $pending${NC}"
    echo ""
    
    db_query_table "SELECT w.id, m.name, w.amount, w.created_at 
                     FROM withdrawals w 
                     JOIN managers m ON m.id = w.manager_id 
                     WHERE w.status='pending'"
    
    echo ""
    read -p "ID заявки для проверки (0 - выход): " wid
    
    if [ "$wid" = "0" ] || [ -z "$wid" ]; then
        return
    fi
    
    local w=$(db_query "SELECT * FROM withdrawals WHERE id=$wid AND status='pending'")
    if [ -z "$w" ]; then
        echo -e "${RED}❌ Заявка не найдена${NC}"
        sleep 1
        return
    fi
    
    local manager_id=$(echo "$w" | cut -d'|' -f2)
    local amount=$(echo "$w" | cut -d'|' -f3)
    
    echo ""
    echo -e "${BLUE}Сумма: ${GREEN}${amount}G${NC}"
    echo -e "${BLUE}Менеджер: ${GREEN}$(db_query "SELECT name FROM managers WHERE id=$manager_id")${NC}"
    echo ""
    
    echo -e "${GREEN}1${NC}) ✅ Подтвердить вывод"
    echo -e "${RED}2${NC}) ❌ Отклонить (вернуть средства)"
    echo -e "${YELLOW}3${NC}) ↪️  Пропустить"
    echo ""
    read -p "Выберите действие: " decision
    
    case $decision in
        1)
            db_query "UPDATE withdrawals SET status='completed', updated_at=datetime('now') WHERE id=$wid"
            
            # Уведомление менеджеру
            db_query "INSERT INTO notifications (manager_id, message) 
                      VALUES ($manager_id, '✅ Ваша заявка на вывод ${amount}G подтверждена!')"
            
            echo -e "${GREEN}✅ Вывод подтвержден!${NC}"
            log "INFO" "Подтвержден вывод #$wid ($CURRENT_USER_NAME)"
            ;;
        2)
            db_query "UPDATE withdrawals SET status='rejected', updated_at=datetime('now') WHERE id=$wid"
            
            # Возврат средств
            local current_balance=$(db_query "SELECT balance FROM managers WHERE id=$manager_id")
            local new_balance=$(echo "$current_balance + $amount" | bc)
            db_query "UPDATE managers SET balance=$new_balance WHERE id=$manager_id"
            db_query "INSERT INTO balance_ledger (manager_id, amount, reason, reference_id) 
                      VALUES ($manager_id, $amount, 'withdrawal_refund', $wid)"
            
            # Уведомление менеджеру
            db_query "INSERT INTO notifications (manager_id, message) 
                      VALUES ($manager_id, '❌ Ваша заявка на вывод ${amount}G отклонена. Средства возвращены на баланс.')"
            
            echo -e "${RED}❌ Вывод отклонен, средства возвращены${NC}"
            log "INFO" "Отклонен вывод #$wid ($CURRENT_USER_NAME)"
            ;;
        3)
            echo -e "${YELLOW}↪️  Пропущено${NC}"
            ;;
        *)
            echo -e "${RED}Неверный выбор${NC}"
            ;;
    esac
    
    sleep 2
}

# ============================================================
# СКРИПТЫ
# ============================================================

scripts_menu() {
    while true; do
        clear
        print_header
        echo -e "${YELLOW}📝 СКРИПТЫ${NC}"
        echo ""
        echo "  ${GREEN}1${NC}) 📋 Список скриптов"
        echo "  ${GREEN}2${NC}) ➕ Добавить скрипт"
        echo "  ${GREEN}3${NC}) 🔄 Вкл/Выкл"
        echo "  ${GREEN}4${NC}) ↩️  Назад"
        echo ""
        read -p "Выберите действие: " choice
        
        case $choice in
            1) scripts_list ;;
            2) scripts_add ;;
            3) scripts_toggle ;;
            4) return ;;
            *) echo -e "${RED}Неверный выбор${NC}" ;;
        esac
    done
}

scripts_list() {
    clear
    print_header
    echo -e "${YELLOW}📝 СПИСОК СКРИПТОВ${NC}"
    echo ""
    
    db_query_table "SELECT id, label, body, is_active, created_at FROM scripts ORDER BY id"
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

scripts_add() {
    clear
    print_header
    echo -e "${YELLOW}➕ ДОБАВЛЕНИЕ СКРИПТА${NC}"
    echo ""
    
    read -p "Название: " label
    echo "Текст сообщения (введите несколько строк, закончите пустой строкой):"
    body=""
    while IFS= read -r line; do
        [ -z "$line" ] && break
        body="${body}${line}\n"
    done
    
    if [ -z "$label" ] || [ -z "$body" ]; then
        echo -e "${RED}❌ Все поля обязательны${NC}"
        sleep 1
        return
    fi
    
    db_query "INSERT INTO scripts (label, body) VALUES ('$label', '$body')"
    
    echo -e "${GREEN}✅ Скрипт добавлен!${NC}"
    log "INFO" "Добавлен скрипт: $label"
    sleep 1
}

scripts_toggle() {
    clear
    print_header
    echo -e "${YELLOW}🔄 ВКЛ/ВЫКЛ СКРИПТА${NC}"
    echo ""
    
    scripts_list
    echo ""
    read -p "ID скрипта: " id
    
    local current=$(db_query "SELECT is_active FROM scripts WHERE id=$id")
    local new=$((1 - current))
    
    db_query "UPDATE scripts SET is_active=$new WHERE id=$id"
    
    echo -e "${GREEN}✅ Статус изменен${NC}"
    sleep 1
}

# ============================================================
# РЕЙТИНГ
# ============================================================

rating() {
    clear
    print_header
    echo -e "${YELLOW}🏆 РЕЙТИНГ МЕНЕДЖЕРОВ${NC}"
    echo ""
    
    echo -e "${BLUE}📊 Общий рейтинг по всем менеджерам:${NC}"
    echo ""
    
    db_query_table "SELECT 
        m.id,
        m.name,
        COUNT(l.id) as total_leads,
        SUM(CASE WHEN l.status IN ('participated', 'returning') THEN 1 ELSE 0 END) as converted,
        ROUND(CAST(SUM(CASE WHEN l.status IN ('participated', 'returning') THEN 1 ELSE 0 END) AS REAL) / 
        NULLIF(COUNT(l.id), 0) * 100, 1) as conversion_pct,
        m.balance,
        m.total_earned
    FROM managers m
    LEFT JOIN leads l ON l.manager_id = m.id
    WHERE m.role = 'manager'
    GROUP BY m.id
    ORDER BY conversion_pct DESC"
    
    echo ""
    
    # Общая статистика по системе
    echo -e "${BLUE}📊 Общая статистика:${NC}"
    local total_leads=$(db_query "SELECT COUNT(*) FROM leads")
    local total_managers=$(db_query "SELECT COUNT(*) FROM managers WHERE role='manager'")
    local total_participations=$(db_query "SELECT COUNT(*) FROM participations WHERE status='approved'")
    local total_balance=$(db_query "SELECT COALESCE(SUM(balance), 0) FROM managers WHERE role='manager'")
    local total_debt=$(db_query "SELECT COALESCE(SUM(balance), 0) FROM leads")
    
    echo -e "  ${WHITE}Всего лидов:${NC} $total_leads"
    echo -e "  ${WHITE}Менеджеров:${NC} $total_managers"
    echo -e "  ${WHITE}Всего участий:${NC} $total_participations"
    echo -e "  ${WHITE}Общий баланс менеджеров:${NC} ${total_balance}G"
    echo -e "  ${YELLOW}Общий долг перед лидами:${NC} ${total_debt}G"
    
    # Расчет средней конверсии
    if [ $total_leads -gt 0 ]; then
        local avg_conv=$(echo "scale=1; ($total_participations * 100) / $total_leads" | bc)
        echo -e "  ${WHITE}Средняя конверсия:${NC} ${avg_conv}%"
    fi
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

# ============================================================
# ЖУРНАЛ
# ============================================================

journal() {
    clear
    print_header
    echo -e "${YELLOW}📜 ЖУРНАЛ ДЕЙСТВИЙ${NC}"
    echo ""
    
    if [ "$CURRENT_USER_ROLE" = "admin" ]; then
        db_query_table "SELECT datetime(created_at,'localtime') as time, action, details FROM activity_log ORDER BY id DESC LIMIT 100"
    else
        db_query_table "SELECT datetime(created_at,'localtime') as time, action, details FROM activity_log WHERE manager_id=$CURRENT_USER_ID ORDER BY id DESC LIMIT 50"
    fi
    
    echo ""
    read -p "Нажмите Enter для продолжения..."
}

# ============================================================
# УВЕДОМЛЕНИЯ
# ============================================================

notifications() {
    clear
    print_header
    echo -e "${YELLOW}🔔 УВЕДОМЛЕНИЯ${NC}"
    echo ""
    
    local unread=$(db_query "SELECT COUNT(*) FROM notifications WHERE manager_id=$CURRENT_USER_ID AND is_read=0")
    echo -e "${BLUE}Непрочитанных: ${YELLOW}$unread${NC}"
    echo ""
    
    db_query_table "SELECT id, message, is_read, created_at FROM notifications 
                     WHERE manager_id=$CURRENT_USER_ID ORDER BY id DESC LIMIT 20"
    
    echo ""
    echo -e "${GREEN}1${NC}) ✅ Отметить все как прочитанные"
    echo -e "${YELLOW}2${NC}) ↪️  Назад"
    echo ""
    read -p "Выберите действие: " choice
    
    case $choice in
        1)
            db_query "UPDATE notifications SET is_read=1 WHERE manager_id=$CURRENT_USER_ID"
            echo -e "${GREEN}✅ Все уведомления прочитаны${NC}"
            sleep 1
            ;;
        2)
            return
            ;;
        *)
            echo -e "${RED}Неверный выбор${NC}"
            sleep 1
            ;;
    esac
}

# ============================================================
# НАСТРОЙКИ
# ============================================================

settings() {
    if [ "$CURRENT_USER_ROLE" != "admin" ]; then
        echo -e "${RED}❌ Доступ запрещен (только админ)${NC}"
        sleep 1
        return
    fi
    
    clear
    print_header
    echo -e "${YELLOW}⚙️  НАСТРОЙКИ${NC}"
    echo ""
    
    echo -e "${BLUE}Текущие настройки:${NC}"
    cat "$CONFIG_FILE"
    echo ""
    
    echo "  1) Изменить комиссию"
    echo "  2) Изменить мин. вывод"
    echo "  3) Изменить штраф за ошибку"
    echo "  4) Назад"
    echo ""
    read -p "Выберите действие: " choice
    
    case $choice in
        1)
            read -p "Новая комиссия (%): " val
            sed -i "s/COMMISSION_PCT=.*/COMMISSION_PCT=$val/" "$CONFIG_FILE"
            echo -e "${GREEN}✅ Обновлено${NC}"
            ;;
        2)
            read -p "Новый минимум вывода: " val
            sed -i "s/MIN_WITHDRAWAL=.*/MIN_WITHDRAWAL=$val/" "$CONFIG_FILE"
            echo -e "${GREEN}✅ Обновлено${NC}"
            ;;
        3)
            read -p "Новый штраф за ошибку: " val
            sed -i "s/PENALTY_AMOUNT=.*/PENALTY_AMOUNT=$val/" "$CONFIG_FILE"
            echo -e "${GREEN}✅ Обновлено${NC}"
            ;;
        4)
            return
            ;;
        *)
            echo -e "${RED}Неверный выбор${NC}"
            ;;
    esac
    
    # Перезагружаем конфиг
    source "$CONFIG_FILE"
    sleep 1
}

# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

main() {
    init
    
    echo -e "${GREEN}✅ Система готова${NC}"
    sleep 1
    
    while true; do
        # Проверка сессии
        if ! check_session; then
            if ! login; then
                echo -e "${RED}❌ Не удалось войти в систему${NC}"
                exit 1
            fi
        fi
        
        while true; do
            clear
            print_header
            
            echo -e "${BLUE}👤 Пользователь:${NC} $CURRENT_USER_NAME"
            echo -e "${BLUE}🎯 Роль:${NC} $CURRENT_USER_ROLE"
            echo -e "${BLUE}💰 Баланс:${NC} ${GREEN}${CURRENT_USER_BALANCE:-0}G${NC}"
            
            # Проверка непрочитанных уведомлений
            local unread=$(db_query "SELECT COUNT(*) FROM notifications WHERE manager_id=$CURRENT_USER_ID AND is_read=0")
            if [ "$unread" -gt 0 ]; then
                echo -e "${YELLOW}🔔 У вас $unread непрочитанных уведомлений!${NC}"
            fi
            echo ""
            
            print_menu
            read -p "Выберите действие: " choice
            
            case $choice in
                1) leads_menu ;;
                2) managers_menu ;;
                3) raffles_menu ;;
                4) withdrawals_menu ;;
                5) scripts_menu ;;
                6) rating ;;
                7) journal ;;
                8) notifications ;;
                9) settings ;;
                0) 
                    logout
                    if [ -f "$SESSION_FILE" ]; then
                        rm -f "$SESSION_FILE"
                    fi
                    echo -e "${GREEN}👋 До свидания!${NC}"
                    log "INFO" "Выход из системы: $CURRENT_USER_NAME"
                    exit 0
                    ;;
                *) echo -e "${RED}Неверный выбор${NC}" ;;
            esac
        done
    done
}

# ============================================================
# ЗАПУСК
# ============================================================

# Проверка наличия sqlite3
if ! command -v sqlite3 &> /dev/null; then
    echo -e "${RED}❌ Ошибка: sqlite3 не установлен${NC}"
    echo "Установите: apt-get install sqlite3 или brew install sqlite3"
    exit 1
fi

# Проверка наличия bc
if ! command -v bc &> /dev/null; then
    echo -e "${YELLOW}⚠️  bc не установлен, установите для работы с дробными числами${NC}"
fi

# Проверка наличия открытых сессий
if [ -f "$SESSION_FILE" ]; then
    rm -f "$SESSION_FILE"
fi

# Запуск
main