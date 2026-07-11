"""Lead CRM — configuration."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _bool(name, default="false"):
    return os.getenv(name, default).lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    DEBUG = _bool("DEBUG", "false")
    ENV = os.getenv("ENVIRONMENT", "development")

    DATABASE_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "leadcrm.db"))

    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = int(os.getenv("PORT", "5100"))

    SESSION_LIFETIME_HOURS = int(os.getenv("SESSION_LIFETIME_HOURS", "168"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", "false")

    ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

    APP_NAME = os.getenv("APP_NAME", "Lead CRM")

    # Уведомления о рисках в Telegram (опционально). Если не задано —
    # уведомления просто не отправляются, остальной функционал не затронут.
    # Получить токен: @BotFather в Telegram. Получить chat_id: написать
    # боту, затем открыть https://api.telegram.org/bot<TOKEN>/getUpdates
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # Email-уведомления (опционально, альтернатива/дополнение к Telegram).
    # Без настроек просто не отправляются.
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

    # Шифрование ПДн (ФИО/email менеджеров) в базе — опционально, требует
    # `pip install cryptography`. Ключ сгенерировать один раз:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Без ключа шифрование просто выключено (поля хранятся как раньше,
    # открытым текстом) — это НЕ имитация шифрования слабым самодельным
    # шифром, а честное "выключено, пока не настроено".
    PII_ENCRYPTION_KEY = os.getenv("PII_ENCRYPTION_KEY", "")

    # S3-совместимое облако для бэкапов (опционально, требует `pip install
    # boto3`). Без настроек бэкапы остаются только на диске, как раньше.
    S3_BACKUP_BUCKET = os.getenv("S3_BACKUP_BUCKET", "")
    S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")  # для не-AWS (напр. Backblaze/MinIO)
    S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
    S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")

    # Ограничение доступа к админке по IP (опционально). Список через
    # запятую, поддерживает CIDR (напр. "1.2.3.4,10.0.0.0/24"). Пусто = не
    # ограничено (как сейчас).
    ADMIN_IP_ALLOWLIST = os.getenv("ADMIN_IP_ALLOWLIST", "")

    # Push-уведомления в браузере (опционально, требует `pip install
    # pywebpush`). Ключи сгенерировать один раз:
    #   python -c "from py_vapid import Vapid01; v=Vapid01(); v.generate_keys(); print(v.private_pem())"
    # Без ключей пуши просто не отправляются — сайт продолжает работать
    # как обычная страница без push-подписки.
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "admin@example.com")