"""Security helpers — scrypt password hashing, stdlib CSRF, rate limiting,
role-based access. Same battle-tested pattern as the studio CRM project.
"""
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 14, 8, 1
    derived = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        derived = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=len(expected))
        return hmac.compare_digest(derived, expected)
    except (ValueError, AttributeError):
        return False


def current_manager_id():
    return session.get("manager_id")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("manager_id"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("manager_id"):
            return redirect(url_for("auth.login", next=request.path))
        if session.get("role") != "admin":
            return jsonify(error="Forbidden"), 403
        return view(*args, **kwargs)
    return wrapped


def ip_allowed(ip: str, allowlist: list) -> bool:
    """Проверяет IP против списка разрешённых адресов/подсетей (CIDR).
    На стандартной библиотеке (ipaddress), без внешних пакетов."""
    import ipaddress
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        entry = entry.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def get_rate_limit_snapshot():
    """Текущее состояние всех rate-limit бакетов — для админ-дашборда.
    Не хранит абсолютное время (только monotonic для самого throttling),
    поэтому показываем только «сколько попыток сейчас активно в окне»,
    а не конкретные метки времени."""
    now = time.monotonic()
    snapshot = []
    for (view_name, client), bucket in _hits.items():
        active = [t for t in bucket if now - t < 3600]  # последний час
        if active:
            snapshot.append({"view": view_name, "client": client, "hits_last_hour": len(active)})
    snapshot.sort(key=lambda r: r["hits_last_hour"], reverse=True)
    return snapshot


def teamlead_required(view):
    """Пускает admin и teamlead. Сама вьюха отвечает за то, чтобы
    teamlead видел только свою команду (роль сама по себе не сужает
    выборку — это делает каждый конкретный маршрут, см. managers.py)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("manager_id"):
            return redirect(url_for("auth.login", next=request.path))
        if session.get("role") not in ("admin", "teamlead"):
            return jsonify(error="Forbidden"), 403
        return view(*args, **kwargs)
    return wrapped


def trainer_required(view):
    """Как login_required, но для менеджеров (не для admin) дополнительно
    требует пройденный тренажёр (managers.trainer_passed=1) — иначе
    редиректит на /simulator/ с объяснением. Админы всегда проходят."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("manager_id"):
            return redirect(url_for("auth.login", next=request.path))
        if session.get("role") != "admin":
            from flask import flash
            from .db import query_one
            row = query_one("SELECT trainer_passed FROM managers WHERE id=?", (session["manager_id"],))
            passed = bool(row and row["trainer_passed"])
            if not passed:
                flash("Сначала пройди тренажёр (нужно набрать 450+/500) — после этого откроется доступ к лидам.", "error")
                return redirect(url_for("simulator.index"))
        return view(*args, **kwargs)
    return wrapped


# --- CSRF (stdlib only) ------------------------------------------------------

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def csrf_token() -> str:
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


def csrf_field():
    from markupsafe import Markup
    token = csrf_token()
    return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')


def csrf_protect():
    from flask import current_app
    if current_app.testing:
        return None
    if request.method in _SAFE_METHODS:
        return None
    expected = session.get("_csrf_token")
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return jsonify(error="Invalid or missing CSRF token"), 400
    return None


# --- Rate limiting (stdlib, in-process sliding window) ----------------------

_hits = defaultdict(deque)


def reset_rate_limits():
    _hits.clear()


def _client_key():
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "unknown")


def rate_limit(max_calls: int, window_seconds: int):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            key = (view.__name__, _client_key())
            now = time.monotonic()
            bucket = _hits[key]
            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()
            if len(bucket) >= max_calls:
                resp = jsonify(error="Слишком много попыток. Подождите немного.")
                resp.status_code = 429
                return resp
            bucket.append(now)
            return view(*args, **kwargs)
        return wrapped
    return decorator
