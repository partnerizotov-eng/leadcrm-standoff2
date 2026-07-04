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
