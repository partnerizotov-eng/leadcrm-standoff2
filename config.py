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