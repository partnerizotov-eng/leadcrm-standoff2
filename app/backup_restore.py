"""Восстановление данных из JSON-бэкапа (см. backup_scheduler.py) в текущую базу.

ВАЖНО, прочитать перед использованием:

- Бэкап содержит только «ключевые» бизнес-таблицы (см. KEY_TABLES в
  backup_scheduler.py) — это НЕ полный дамп базы. Таблицы вроде scripts,
  notifications, support_tickets, achievements бэкапом не покрываются и
  этим восстановлением не затрагиваются.

- Пароли менеджеров в бэкап не попадают (сознательно вырезаны при экспорте
  ради безопасности). При восстановлении:
    * если менеджер с таким id уже есть в текущей базе — его password_hash
      НЕ трогаем, обновляем только остальные поля;
    * если менеджера с таким id в текущей базе нет — создаём его с новым
      случайным паролем и возвращаем этот пароль в отчёте, чтобы админ
      мог передать его менеджеру.

- Никаких DELETE и никакого INSERT OR REPLACE: только точечный UPDATE по id
  (если строка уже есть) или INSERT (если её нет). Это осознанный выбор —
  REPLACE в SQLite при конфликте по любому UNIQUE-полю (не только id) может
  каскадно удалить чужую, не связанную с бэкапом строку и утащить за собой
  её дочерние записи. Здесь так рисковать нельзя — это финансовые данные.

- Перед любыми изменениями автоматически создаётся свежий бэкап ТЕКУЩЕГО
  состояния базы — чтобы всегда можно было откатиться, если что-то пошло
  не так уже после восстановления.

- Всё восстановление — одна транзакция на верхнем уровне; но отдельные
  строки, вызвавшие конфликт (например, дубликат уникального vk_id под
  другим id), не прерывают процесс целиком — они просто пропускаются и
  попадают в отчёт как conflicts, чтобы админ разобрался вручную.
"""
import secrets

from .backup_scheduler import create_backup
from .db import get_db, transaction
from .security import hash_password

# Порядок важен из-за внешних ключей: сначала родители, потом дети.
RESTORE_ORDER = [
    "managers",
    "leads",
    "contests",
    "submissions",
    "manager_ledger",
    "balance_ledger",
    "withdrawals",
    "withdrawal_events",
    "contest_winners",
    "referrals",
    "referral_claims",
    # Добавлено вместе с новыми функциями этой сессии — их внешние ключи
    # (managers/leads) уже удовлетворены таблицами выше по списку.
    "lead_notes",
    "canned_responses",
    "shifts",
    "balance_adjustments",
    "login_log",
    "admin_ip_allowlist",
    "rating_seasons",
]


def _existing_columns(db, table):
    return {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _restore_generic_row(db, table, row, report):
    """UPDATE по id, если строка уже есть; иначе INSERT. Никогда не REPLACE/DELETE."""
    cols = _existing_columns(db, table)
    row = {k: v for k, v in row.items() if k in cols}
    if "id" not in row:
        return 0
    row_id = row["id"]
    try:
        exists = db.execute(f"SELECT 1 FROM {table} WHERE id=?", (row_id,)).fetchone()
        if exists:
            set_cols = [k for k in row.keys() if k != "id"]
            if not set_cols:
                return 0
            set_clause = ", ".join(f"{k}=?" for k in set_cols)
            db.execute(f"UPDATE {table} SET {set_clause} WHERE id=?",
                       [row[k] for k in set_cols] + [row_id])
        else:
            keys = list(row.keys())
            placeholders = ", ".join("?" for _ in keys)
            col_list = ", ".join(keys)
            db.execute(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
                       [row[k] for k in keys])
        return 1
    except Exception as e:
        report["conflicts"].append(f"{table}#{row_id}: {e}")
        return 0


def _restore_manager_row(db, row, report):
    """Как generic, но с двумя отличиями:
    - password_hash и все поля 2FA (totp_*) никогда не перезаписываются у
      уже существующих менеджеров — ровно тот же принцип: бэкап их и не
      содержит (totp_secret/backup_codes сознательно вырезаны при
      создании бэкапа, см. backup_scheduler.py), трогать чужое состояние
      безопасности нельзя.
    - у НОВЫХ менеджеров генерируется временный пароль, а 2FA всегда
      принудительно выключается (totp_enabled=0), даже если в бэкапе
      было totp_enabled=1 — иначе получится менеджер с "включённой" 2FA,
      но без секрета для проверки кода: пароль верный, а зайти
      невозможно НИКОГДА, это перманентная блокировка аккаунта."""
    cols = _existing_columns(db, "managers")
    row = {k: v for k, v in row.items() if k in cols}
    if "id" not in row:
        return 0
    manager_id = row["id"]
    row.pop("password_hash", None)
    row.pop("totp_secret", None)
    row.pop("totp_backup_codes", None)
    row.pop("totp_enabled", None)

    try:
        existing = db.execute("SELECT id FROM managers WHERE id=?", (manager_id,)).fetchone()
        if existing:
            set_cols = [k for k in row.keys() if k != "id"]
            if set_cols:
                set_clause = ", ".join(f"{k}=?" for k in set_cols)
                db.execute(f"UPDATE managers SET {set_clause} WHERE id=?",
                           [row[k] for k in set_cols] + [manager_id])
            return 1
        else:
            temp_password = secrets.token_urlsafe(6)
            row["password_hash"] = hash_password(temp_password)
            row["totp_enabled"] = 0  # без секрета — принудительно выключено, см. докстринг
            keys = list(row.keys())
            placeholders = ", ".join("?" for _ in keys)
            col_list = ", ".join(keys)
            db.execute(f"INSERT INTO managers ({col_list}) VALUES ({placeholders})",
                       [row[k] for k in keys])
            report["new_managers"].append({
                "id": manager_id,
                "login": row.get("login", "?"),
                "temp_password": temp_password,
            })
            return 1
    except Exception as e:
        report["conflicts"].append(f"managers#{manager_id}: {e}")
        return 0


def validate_backup_shape(data) -> str | None:
    """Возвращает текст ошибки, если файл не похож на наш бэкап, иначе None."""
    if not isinstance(data, dict):
        return "Файл не является JSON-объектом — это не бэкап LeadCRM."
    if "created_at" not in data:
        return "В файле нет поля created_at — не похоже на бэкап LeadCRM."
    if not any(k in data for k in RESTORE_ORDER):
        return "В файле нет ни одной из ожидаемых таблиц — не похоже на бэкап LeadCRM."
    return None


def restore_backup(data: dict) -> dict:
    """Восстанавливает таблицы из словаря бэкапа в текущую базу.

    Возвращает отчёт:
      {
        "safety_backup": "backup_....json" | None,
        "tables": {"managers": 12, "leads": 53, ...},
        "new_managers": [{"id":.., "login":.., "temp_password":..}, ...],
        "conflicts": ["leads#41: UNIQUE constraint failed: leads.vk_id", ...],
        "errors": [...],
      }
    """
    report = {"safety_backup": None, "tables": {}, "new_managers": [], "conflicts": [], "errors": []}

    # Страховка: бэкапим текущее состояние ДО того, как что-либо менять.
    # Если это не удалось — восстановление не запускаем, слишком рискованно.
    try:
        report["safety_backup"] = create_backup()
    except Exception as e:
        report["errors"].append(f"Не удалось создать safety-бэкап текущего состояния — восстановление отменено: {e}")
        return report

    with transaction() as db:
        for table in RESTORE_ORDER:
            rows = data.get(table)
            if not isinstance(rows, list):
                continue
            restored = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if table == "managers":
                    restored += _restore_manager_row(db, row, report)
                else:
                    restored += _restore_generic_row(db, table, row, report)
            report["tables"][table] = restored

    return report
