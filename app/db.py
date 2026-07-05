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

CREATE TABLE IF NOT EXISTS manager_settings (
    manager_id INTEGER NOT NULL,
    key        TEXT    NOT NULL,
    value      TEXT,
    updated_at TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (manager_id, key),
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE
);

-- ==================== НОВЫЕ ТАБЛИЦЫ ДЛЯ АДМИН ФУНКЦИЙ ====================

CREATE TABLE IF NOT EXISTS balance_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id    INTEGER NOT NULL,
    amount_change REAL    NOT NULL,
    reason        TEXT    NOT NULL,
    admin_id      INTEGER NOT NULL,
    created_at    TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_balance_logs_manager ON balance_logs(manager_id);

CREATE TABLE IF NOT EXISTS player_balance_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     INTEGER NOT NULL,
    vk_id       TEXT,
    amount      REAL    NOT NULL,
    reason      TEXT    NOT NULL,
    admin_id    INTEGER NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_player_balance_logs_lead ON player_balance_logs(lead_id);

CREATE TABLE IF NOT EXISTS deleted_leads_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id        INTEGER NOT NULL,
    lead_name      TEXT    NOT NULL,
    lead_vk_id     TEXT,
    manager_id     INTEGER NOT NULL,
    admin_comment  TEXT,
    admin_id       INTEGER NOT NULL,
    deleted_at     TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_deleted_leads_log_manager ON deleted_leads_log(manager_id);

CREATE TABLE IF NOT EXISTS payment_proofs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    withdrawal_id INTEGER,
    file_path   TEXT    NOT NULL,
    description TEXT    NOT NULL,
    admin_id    INTEGER NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (withdrawal_id) REFERENCES withdrawals(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_id) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_payment_proofs_withdrawal ON payment_proofs(withdrawal_id);

CREATE TABLE IF NOT EXISTS top_player_photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT    NOT NULL,
    description TEXT    NOT NULL,
    admin_id    INTEGER NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (admin_id) REFERENCES managers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS manager_stats (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_id           INTEGER NOT NULL UNIQUE,
    total_leads          INTEGER DEFAULT 0,
    converted_leads      INTEGER DEFAULT 0,
    total_withdrawals    REAL    DEFAULT 0,
    approved_withdrawals REAL    DEFAULT 0,
    balance              REAL    DEFAULT 0,
    last_updated         TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS message_scripts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    created_by  INTEGER NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now')),
    is_active   INTEGER DEFAULT 1,
    FOREIGN KEY (created_by) REFERENCES managers(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_message_scripts_category ON message_scripts(category);

CREATE TABLE IF NOT EXISTS script_usage_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id   INTEGER NOT NULL,
    manager_id  INTEGER NOT NULL,
    lead_id     INTEGER,
    vk_id       TEXT,
    used_at     TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (script_id) REFERENCES message_scripts(id) ON DELETE CASCADE,
    FOREIGN KEY (manager_id) REFERENCES managers(id) ON DELETE CASCADE,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
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
        ("leads", "game_rank", "ALTER TABLE leads ADD COLUMN game_rank TEXT DEFAULT ''"),
        ("leads", "game_stats", "ALTER TABLE leads ADD COLUMN game_stats TEXT DEFAULT '{}'"),
        ("leads", "game_verified", "ALTER TABLE leads ADD COLUMN game_verified INTEGER NOT NULL DEFAULT 0"),
        ("leads", "game_verified_at", "ALTER TABLE leads ADD COLUMN game_verified_at TEXT"),
        ("scripts", "category", "ALTER TABLE scripts ADD COLUMN category TEXT DEFAULT 'Другое'"),
        ("withdrawals", "payment_proof_id", "ALTER TABLE withdrawals ADD COLUMN payment_proof_id INTEGER"),
        ("withdrawals", "payout_confirmed", "ALTER TABLE withdrawals ADD COLUMN payout_confirmed INTEGER NOT NULL DEFAULT 0"),
        ("withdrawals", "payout_screenshot", "ALTER TABLE withdrawals ADD COLUMN payout_screenshot TEXT"),
        ("withdrawals", "payout_admin_confirmed", "ALTER TABLE withdrawals ADD COLUMN payout_admin_confirmed INTEGER NOT NULL DEFAULT 0"),
        ("withdrawals", "payout_admin_screenshot", "ALTER TABLE withdrawals ADD COLUMN payout_admin_screenshot TEXT"),
        ("withdrawals", "payout_admin_comment", "ALTER TABLE withdrawals ADD COLUMN payout_admin_comment TEXT"),
        ("support_messages", "attachment_path", "ALTER TABLE support_messages ADD COLUMN attachment_path TEXT"),
        ("support_messages", "attachment_type", "ALTER TABLE support_messages ADD COLUMN attachment_type TEXT"),
        ("managers", "email", "ALTER TABLE managers ADD COLUMN email TEXT"),
        ("managers", "vk_url", "ALTER TABLE managers ADD COLUMN vk_url TEXT"),
        ("managers", "game_id", "ALTER TABLE managers ADD COLUMN game_id TEXT"),
        ("managers", "profile_completed", "ALTER TABLE managers ADD COLUMN profile_completed INTEGER NOT NULL DEFAULT 0"),
        ("managers", "consent_given_at", "ALTER TABLE managers ADD COLUMN consent_given_at TEXT"),
    ]
    for table, column, ddl in migrations:
        if not _column_exists(conn, table, column):
            try:
                conn.execute(ddl)
            except:
                pass
    
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
