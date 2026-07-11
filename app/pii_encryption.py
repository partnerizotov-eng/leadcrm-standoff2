"""Шифрование ПДн (конкретно — email менеджеров) в базе.

Честная оговорка: в стандартной библиотеке Python нет надёжного
симметричного шифрования (hashlib/hmac — это хэши и MAC, НЕ шифрование,
они необратимы и для этой задачи не подходят). Городить самодельный шифр
на голом stdlib означало бы ложную безопасность — хуже, чем её отсутствие,
потому что создаёт иллюзию защиты. Поэтому здесь — честно опциональная
зависимость: `pip install cryptography`, ключ в PII_ENCRYPTION_KEY.

Без ключа/пакета encrypt_field()/decrypt_field() — прозрачный no-op,
поле хранится как раньше, открытым текстом. Это НЕ имитация шифрования,
а явное "выключено, пока не настроено".

Сгенерировать ключ один раз:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from flask import current_app

_PREFIX = "enc:"  # маркер зашифрованного значения — отличает от старых plaintext-строк


def is_pii_encryption_configured() -> bool:
    if not current_app.config.get("PII_ENCRYPTION_KEY"):
        return False
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _fernet():
    from cryptography.fernet import Fernet
    key = current_app.config["PII_ENCRYPTION_KEY"].encode()
    return Fernet(key)


def encrypt_field(value: str) -> str:
    """Шифрует строку. Если шифрование не настроено — возвращает значение
    как есть (открытым текстом, как было раньше)."""
    if not value or not is_pii_encryption_configured():
        return value
    token = _fernet().encrypt(value.encode()).decode()
    return _PREFIX + token


def decrypt_field(value: str) -> str:
    """Расшифровывает строку, если она зашифрована (есть маркер _PREFIX).
    Если не зашифрована (старые данные до включения шифрования, или
    шифрование выключено) — возвращает как есть, без ошибок."""
    if not value or not value.startswith(_PREFIX):
        return value
    if not is_pii_encryption_configured():
        # Шифрование выключили, а данные ещё зашифрованы старым ключом —
        # честно возвращаем как есть, а не падаем и не показываем мусор.
        return value
    try:
        from cryptography.fernet import InvalidToken
        return _fernet().decrypt(value[len(_PREFIX):].encode()).decode()
    except Exception:
        return value  # неверный ключ / битые данные — не роняем страницу
