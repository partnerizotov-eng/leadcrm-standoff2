"""Периодический бэкап ключевых бизнес-данных — раз в 6 часов, автоматически,
прямо из работающего приложения, без внешних сервисов.

⚠️ Важно: файлы бэкапа хранятся на том же диске, что и сама база. Если диск
эфемерный и обнуляется при передеплое — бэкапы обнулятся вместе с базой.
Это защищает от багов/ошибок/случайного удаления между передеплоями, но
НЕ заменяет выгрузку бэкапа во внешнее хранилище перед каждым git push."""
import json
import os
from datetime import datetime

from flask import current_app

from .db import query_all

KEY_TABLES = [
    "managers", "leads", "submissions", "withdrawals", "withdrawal_events",
    "manager_ledger", "balance_ledger", "referrals", "referral_claims",
    "contests", "contest_winners",
    # Добавлено вместе с новыми функциями этой сессии:
    "lead_notes", "canned_responses", "shifts", "balance_adjustments",
    "admin_ip_allowlist", "rating_seasons", "login_log",
    # Осознанно НЕ включены: active_sessions и push_subscriptions —
    # это эфемерные данные, привязанные к конкретному браузеру/cookie
    # на конкретный момент, восстанавливать их бессмысленно (сессии всё
    # равно инвалидируются, push-подписки протухают без повторной
    # регистрации в браузере).
]

MAX_BACKUPS_KEPT = 40  # 40 * 6ч ≈ 10 дней истории


def _backups_dir():
    path = os.path.join(current_app.root_path, "..", "backups")
    os.makedirs(path, exist_ok=True)
    return path


def create_backup():
    """Собирает ключевые таблицы в один JSON-файл. Пароли и секреты 2FA
    не сохраняются ни при каких условиях — если бы файл бэкапа утёк,
    totp_secret/резервные коды позволили бы пройти вход в обход второго
    фактора, это тот же риск, что и пароль."""
    data = {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    for table in KEY_TABLES:
        try:
            if table == "login_log":
                # Без ограничения эта таблица росла бы бесконечно (запись
                # на каждую попытку входа) — бэкапы бы разбухали со
                # временем. Держим только последние 90 дней, этого
                # достаточно для аудита, а старое всё равно ушло бы в
                # предыдущие бэкапы.
                rows = query_all("SELECT * FROM login_log WHERE created_at >= datetime('now', '-90 days')")
            else:
                rows = query_all(f"SELECT * FROM {table}")
            records = [dict(r) for r in rows]
            if table == "managers":
                for r in records:
                    r.pop("password_hash", None)
                    r.pop("totp_secret", None)
                    r.pop("totp_backup_codes", None)
            data[table] = records
        except Exception as e:
            data[table] = {"error": str(e)}

    filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(_backups_dir(), filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    _prune_old_backups()
    _try_upload_to_s3(filepath, filename)
    return filename


def _try_upload_to_s3(filepath, filename):
    """Дублирует бэкап в S3-совместимое хранилище — опционально, требует
    `pip install boto3` и S3_BACKUP_BUCKET в .env. Без настроек просто
    ничего не делает — бэкап остаётся только на диске, как раньше.
    Никогда не бросает исключение наружу (best-effort, как Telegram/email)."""
    try:
        from flask import current_app
        c = current_app.config
        if not c.get("S3_BACKUP_BUCKET"):
            return False
        import boto3
        client = boto3.client(
            "s3",
            endpoint_url=c.get("S3_ENDPOINT_URL") or None,
            aws_access_key_id=c.get("S3_ACCESS_KEY") or None,
            aws_secret_access_key=c.get("S3_SECRET_KEY") or None,
        )
        client.upload_file(filepath, c["S3_BACKUP_BUCKET"], f"leadcrm-backups/{filename}")
        return True
    except ImportError:
        return False  # boto3 не установлен — не страшно, локальный бэкап уже есть
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.warning(f"S3 backup upload failed: {e}")
        except Exception:
            pass
        return False


def _prune_old_backups():
    d = _backups_dir()
    files = sorted(
        (f for f in os.listdir(d) if f.startswith("backup_") and f.endswith(".json")),
        reverse=True,
    )
    for old_file in files[MAX_BACKUPS_KEPT:]:
        try:
            os.remove(os.path.join(d, old_file))
        except OSError:
            pass


def list_backups():
    d = _backups_dir()
    files = sorted(
        (f for f in os.listdir(d) if f.startswith("backup_") and f.endswith(".json")),
        reverse=True,
    )
    result = []
    for f in files:
        full = os.path.join(d, f)
        result.append({
            "name": f,
            "size_kb": round(os.path.getsize(full) / 1024, 1),
            "created": datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return result


def start_backup_scheduler(app):
    """Запускает фоновый планировщик раз в 6 часов. Защищено от двойного
    старта под Flask debug-режимом (там процесс запускается дважды)."""
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return
    if getattr(app, "_backup_scheduler_started", False):
        return
    app._backup_scheduler_started = True

    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True)

    def job():
        with app.app_context():
            try:
                create_backup()
                app.logger.info("✅ Плановый бэкап ключевых данных выполнен")
            except Exception as e:
                app.logger.error(f"❌ Ошибка планового бэкапа: {e}")

    scheduler.add_job(job, "interval", hours=6, next_run_time=datetime.now())
    scheduler.start()
