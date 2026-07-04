"""Database layer — one schema, one source of truth. SQLite, WAL mode."""
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS managers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    login         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'manager',
    is_active     INTEGER DEFAULT 1,
    session_started_at   TEXT,
    total_seconds_worked INTEGER NOT NULL DEFAULT 0,
    balance       REAL    NOT NULL DEFAULT 0,
    total_earned  REAL    NOT NULL DEFAULT 0,
    created_at    TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS leads (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    vk_id             TEXT    NOT NULL UNIQUE,
    vk_url            TEXT    NOT NULL,
    name              TEXT    DEFAULT '',
    source_group      TEXT    DEFAULT '',
    status            TEXT    NOT NULL DEFAULT 'new',
    assigned_manager_id INTEGER,
    game_id           TEXT    DEFAULT '',
    notes             TEXT    DEFAULT '',
    balance           REAL    NOT NULL DEFAULT 0,
    found_at          TEXT    DEFAULT (datetime('now')),
    first_contacted_at TEXT,
    last_status_change TEXT   DEFAULT (datetime('now')),
    participation_count INTEGER DEFAULT 0,
    FOREIGN KEY (assigned_manager_id) REFERENCES managers(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_manager ON leads(assigned_manager_id);
CREATE INDEX IF NOT EXISTS idx_leads_status  ON leads(status);

CREATE TABLE IF NOT EXISTS submissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id       INTEGER NOT NULL,
    manager_id    INTEGER NOT NULL,
    round_date    TEXT    NOT NULL,
    round_slot    TEXT    NOT NULL,
    screenshot    TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'pending',
    admin_comment TEXT    DEFAULT '',
    reviewed_by   INTEGER,
    reviewed_at   TEXT,
    created_at    TEXT    DEFAULT (datetime('now')),
    UNIQUE (lead_id, round_date, round_slot),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE,
    FOREIGN KEY (reviewed_by) REFERENCES managers(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
CREATE INDEX IF NOT EXISTS idx_submissions_manager ON submissions(manager_id);

CREATE TABLE IF NOT EXISTS balance_ledger (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id       INTEGER,
    manager_id    INTEGER,
    amount        REAL    NOT NULL,
    reason        TEXT    NOT NULL,
    reference_id  INTEGER,
    actor_manager_id INTEGER,
    note          TEXT    DEFAULT '',
    created_at    TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ledger_lead ON balance_ledger(lead_id);
CREATE INDEX IF NOT EXISTS idx_ledger_manager ON balance_ledger(manager_id);

CREATE TABLE IF NOT EXISTS manager_ledger (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id    INTEGER NOT NULL,
    amount        REAL    NOT NULL,
    reason        TEXT    NOT NULL,
    reference_id  INTEGER,
    actor_manager_id INTEGER,
    note          TEXT    DEFAULT '',
    created_at    TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_manager_ledger_manager ON manager_ledger(manager_id);

CREATE TABLE IF NOT EXISTS withdrawals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id     INTEGER NOT NULL,
    requested_amount REAL  NOT NULL,
    commission_pct REAL    NOT NULL DEFAULT 20,
    list_price     REAL    NOT NULL DEFAULT 0,
    status         TEXT    NOT NULL DEFAULT 'pending',
    created_at     TEXT    DEFAULT (datetime('now')),
    updated_at     TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status);

CREATE TABLE IF NOT EXISTS withdrawal_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    withdrawal_id INTEGER NOT NULL,
    actor         TEXT    NOT NULL,
    actor_id      INTEGER,
    message       TEXT    DEFAULT '',
    screenshot    TEXT,
    created_at    TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (withdrawal_id) REFERENCES withdrawals(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id  INTEGER NOT NULL,
    message     TEXT    NOT NULL,
    link        TEXT    DEFAULT '',
    is_read     INTEGER DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_notifications_manager ON notifications(manager_id, is_read);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scripts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    is_active   INTEGER DEFAULT 1,
    created_by  INTEGER,
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (created_by) REFERENCES managers(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS outreach_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL,
    manager_id  INTEGER NOT NULL,
    script_id   INTEGER,
    response    TEXT    DEFAULT 'pending',
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE,
    FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach_log(lead_id);
CREATE INDEX IF NOT EXISTS idx_outreach_manager ON outreach_log(manager_id);

CREATE TABLE IF NOT EXISTS participation_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL,
    round_date  TEXT    NOT NULL,
    round_slot  TEXT    NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    UNIQUE (lead_id, round_date, round_slot)
);

CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id  INTEGER,
    message     TEXT    NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- Игровые аккаунты (Standoff 2)
CREATE TABLE IF NOT EXISTS game_accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id      INTEGER NOT NULL,
    game_id      TEXT    NOT NULL UNIQUE,
    game_name    TEXT    DEFAULT '',
    platform     TEXT    DEFAULT 'standoff2',
    rank         TEXT    DEFAULT 'Новичок',
    level        INTEGER DEFAULT 0,
    hours_played REAL    DEFAULT 0,
    kd_ratio     REAL    DEFAULT 0,
    wins         INTEGER DEFAULT 0,
    balance      REAL    DEFAULT 0,
    verified     INTEGER DEFAULT 0,
    verified_at  TEXT,
    stats        TEXT    DEFAULT '{}',
    created_at   TEXT    DEFAULT (datetime('now')),
    updated_at   TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_game_accounts_lead ON game_accounts(lead_id);
CREATE INDEX IF NOT EXISTS idx_game_accounts_game ON game_accounts(game_id);

-- Выводы голды в игру
CREATE TABLE IF NOT EXISTS game_withdrawals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id        INTEGER NOT NULL,
    manager_id     INTEGER NOT NULL,
    game_id        TEXT    NOT NULL,
    amount         REAL    NOT NULL,
    commission     REAL    DEFAULT 0,
    net_amount     REAL    DEFAULT 0,
    transaction_id TEXT,
    status         TEXT    DEFAULT 'pending',
    error_message  TEXT    DEFAULT '',
    created_at     TEXT    DEFAULT (datetime('now')),
    processed_at   TEXT,
    completed_at   TEXT,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_game_withdrawals_lead ON game_withdrawals(lead_id);
CREATE INDEX IF NOT EXISTS idx_game_withdrawals_manager ON game_withdrawals(manager_id);
CREATE INDEX IF NOT EXISTS idx_game_withdrawals_status ON game_withdrawals(status);

-- Достижения менеджеров
CREATE TABLE IF NOT EXISTS manager_achievements (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id     INTEGER NOT NULL,
    achievement_id TEXT    NOT NULL,
    name           TEXT    NOT NULL,
    description    TEXT,
    icon           TEXT,
    unlocked_at    TEXT    DEFAULT (datetime('now')),
    UNIQUE(manager_id, achievement_id),
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_manager_achievements_manager ON manager_achievements(manager_id);

-- Участия лидов в раундах (для рейтинга игроков)
CREATE TABLE IF NOT EXISTS participations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL,
    manager_id  INTEGER,
    round_date  TEXT,
    round_slot  TEXT,
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_participations_lead ON participations(lead_id);

-- Реферальная система
CREATE TABLE IF NOT EXISTS referrals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id   INTEGER NOT NULL,
    referred_id   INTEGER NOT NULL,
    reward_amount REAL    DEFAULT 0,
    status        TEXT    DEFAULT 'pending',
    created_at    TEXT    DEFAULT (datetime('now')),
    rewarded_at   TEXT,
    UNIQUE(referrer_id, referred_id)
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);
CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals(referred_id);

-- История статусов лидов
CREATE TABLE IF NOT EXISTS lead_status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL,
    status      TEXT    NOT NULL,
    comment     TEXT,
    manager_id  INTEGER,
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_lead_status_lead ON lead_status_history(lead_id);

-- Тикеты поддержки
CREATE TABLE IF NOT EXISTS support_tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id  INTEGER NOT NULL,
    subject     TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'open',
    created_at  TEXT    DEFAULT (datetime('now')),
    updated_at  TEXT    DEFAULT (datetime('now')),
    closed_at   TEXT,
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_support_tickets_manager ON support_tickets(manager_id);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(status);

-- Сообщения в тикетах поддержки
CREATE TABLE IF NOT EXISTS support_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id     INTEGER NOT NULL,
    manager_id    INTEGER,
    admin_id      INTEGER,
    message       TEXT    NOT NULL,
    is_from_admin INTEGER DEFAULT 0,
    is_read       INTEGER DEFAULT 0,
    created_at    TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_support_messages_ticket ON support_messages(ticket_id);

-- Пользовательские настройки менеджеров
CREATE TABLE IF NOT EXISTS manager_settings (
    manager_id INTEGER NOT NULL,
    key        TEXT    NOT NULL,
    value      TEXT,
    updated_at TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (manager_id, key),
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE
);
"""


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE_PATH"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db


def close_db(_exc=None):
    """Закрывает соединение с БД при завершении запроса"""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def execute(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid


@contextmanager
def transaction():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_setting(key, default=None):
    row = query_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    execute("INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def log_activity(message, manager_id=None):
    execute("INSERT INTO activity (manager_id, message) VALUES (?, ?)", (manager_id, message))


def _column_exists(conn, table, column):
    return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _migrate(conn):
    migrations = [
        ("managers", "session_started_at", "ALTER TABLE managers ADD COLUMN session_started_at TEXT"),
        ("managers", "total_seconds_worked",
         "ALTER TABLE managers ADD COLUMN total_seconds_worked INTEGER NOT NULL DEFAULT 0"),
        ("managers", "balance", "ALTER TABLE managers ADD COLUMN balance REAL NOT NULL DEFAULT 0"),
        ("managers", "total_earned", "ALTER TABLE managers ADD COLUMN total_earned REAL NOT NULL DEFAULT 0"),
        # Игровые поля лида (Standoff 2) — используются в game/standoff2/models
        ("leads", "game_rank", "ALTER TABLE leads ADD COLUMN game_rank TEXT DEFAULT ''"),
        ("leads", "game_stats", "ALTER TABLE leads ADD COLUMN game_stats TEXT DEFAULT '{}'"),
        ("leads", "game_verified", "ALTER TABLE leads ADD COLUMN game_verified INTEGER NOT NULL DEFAULT 0"),
        ("leads", "game_verified_at", "ALTER TABLE leads ADD COLUMN game_verified_at TEXT"),
        # Категория скрипта — используется в scripts.py
        ("scripts", "category", "ALTER TABLE scripts ADD COLUMN category TEXT DEFAULT 'Другое'"),
    ]
    for table, column, ddl in migrations:
        if not _column_exists(conn, table, column):
            conn.execute(ddl)
    
    # Проверка на существование manager_id в balance_ledger
    if not _column_exists(conn, "balance_ledger", "manager_id"):
        try:
            conn.execute("ALTER TABLE balance_ledger ADD COLUMN manager_id INTEGER")
        except:
            pass
    
    conn.commit()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()
    _migrate(db)


def ensure_admin():
    """Create the first admin account from config if none exists yet."""
    from .security import hash_password
    cfg = current_app.config
    if query_one("SELECT 1 FROM managers WHERE role='admin'"):
        return
    execute("INSERT INTO managers (login, password_hash, name, role) VALUES (?, ?, ?, 'admin')",
            (cfg["ADMIN_LOGIN"], hash_password(cfg["ADMIN_PASSWORD"]), "Администратор"))