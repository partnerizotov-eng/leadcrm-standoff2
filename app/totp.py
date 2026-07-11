"""TOTP (RFC 6238) — двухфакторная аутентификация, на стандартной
библиотеке, без внешних пакетов вроде pyotp — в духе остального
security.py в этом проекте.

Совместимо с Google Authenticator, Authy, 1Password и любым другим
приложением, поддерживающим стандарт TOTP.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD = 30       # секунд на один код — стандарт де-факто
SECRET_BYTES = 20  # 160 бит — рекомендованный RFC размер секрета


def generate_secret() -> str:
    """Base32-секрет без паддинга — то, что вводится в приложение-аутентификатор."""
    raw = secrets.token_bytes(SECRET_BYTES)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    padded = secret_b32 + "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(code_int).zfill(DIGITS)


def totp_now(secret_b32: str, at=None) -> str:
    """Текущий код — в основном для тестов (реальный код всегда вводит
    пользователь из своего приложения-аутентификатора)."""
    t = int((at if at is not None else time.time()) // PERIOD)
    return _hotp(secret_b32, t)


def verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    """Проверяет код с допуском ±window периодов — компенсирует небольшой
    рассинхрон часов между сервером и телефоном пользователя."""
    if not secret_b32 or not code or not code.isdigit() or len(code) != DIGITS:
        return False
    now_period = int(time.time() // PERIOD)
    for delta in range(-window, window + 1):
        expected = _hotp(secret_b32, now_period + delta)
        if hmac.compare_digest(expected, code):
            return True
    return False


def provisioning_uri(secret_b32: str, account_name: str, issuer: str = "LeadCRM") -> str:
    """otpauth:// URI для QR-кода / ручного добавления в приложение."""
    label = quote(f"{issuer}:{account_name}")
    return (f"otpauth://totp/{label}?secret={secret_b32}"
            f"&issuer={quote(issuer)}&digits={DIGITS}&period={PERIOD}")


def generate_backup_codes(count: int = 8) -> list:
    """Одноразовые резервные коды на случай потери устройства с
    аутентификатором. Показываются пользователю ровно один раз при
    включении 2FA — хранятся только хэши (см. totp_setup.py)."""
    return [f"{secrets.randbelow(10**8):08d}" for _ in range(count)]
