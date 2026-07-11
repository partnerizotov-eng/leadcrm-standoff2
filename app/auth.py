from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .db import execute, log_activity, query_one
from .security import rate_limit, verify_password
from .totp import verify_totp

bp = Blueprint("auth", __name__)


def _client_ip():
    # За обратным прокси (nginx и т.п.) реальный IP приходит в заголовке —
    # без прокси просто берём адрес самого запроса.
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "")


def _complete_login(manager):
    """Открывает полноценную сессию — вызывается либо сразу (если 2FA не
    включена), либо после успешной проверки второго фактора."""
    import secrets as _secrets
    session.clear()
    session.permanent = True
    session["manager_id"] = manager["id"]
    session["role"] = manager["role"]
    session["name"] = manager["name"]

    session_uid = _secrets.token_hex(16)
    session["session_uid"] = session_uid
    execute(
        "INSERT INTO active_sessions (manager_id, session_id, ip_address, user_agent) VALUES (?, ?, ?, ?)",
        (manager["id"], session_uid, _client_ip(), request.headers.get("User-Agent", "")[:255]))

    execute("UPDATE managers SET session_started_at=datetime('now') WHERE id=?", (manager["id"],))
    execute("INSERT INTO login_log (manager_id, login_attempted, ip_address, success) VALUES (?, ?, ?, 1)",
            (manager["id"], manager["login"], _client_ip()))
    log_activity(f"{manager['name']} вошёл в систему.", manager["id"])


def _try_consume_backup_code(manager, code) -> bool:
    """Резервный код — одноразовый вход, если телефон с аутентификатором
    потерян. При успехе код удаляется из списка (больше не сработает)."""
    import json
    from .security import verify_password as verify_pw
    raw = manager["totp_backup_codes"]
    if not raw or not code:
        return False
    try:
        codes = json.loads(raw)
    except (ValueError, TypeError):
        return False
    for i, hashed in enumerate(codes):
        if verify_pw(code, hashed):
            codes.pop(i)
            execute("UPDATE managers SET totp_backup_codes=? WHERE id=?",
                    (json.dumps(codes), manager["id"]))
            return True
    return False


@bp.route("/login", methods=["GET", "POST"])
@rate_limit(max_calls=10, window_seconds=60)
def login():
    if session.get("manager_id"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        login_name = request.form.get("login", "").strip().lower()
        password = request.form.get("password", "")
        manager = query_one("SELECT * FROM managers WHERE login = ? AND is_active = 1", (login_name,))
        if manager and verify_password(password, manager["password_hash"]):
            if manager["totp_enabled"]:
                # Пароль верный, но нужен второй фактор — полноценную
                # сессию (manager_id) пока НЕ открываем, только временную
                # метку "жду код от этого менеджера".
                session.clear()
                session["pending_2fa_manager_id"] = manager["id"]
                session["pending_2fa_next"] = request.args.get("next") or ""
                return redirect(url_for("auth.verify_2fa"))
            _complete_login(manager)
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        execute("INSERT INTO login_log (manager_id, login_attempted, ip_address, success) VALUES (?, ?, ?, 0)",
                ((manager["id"] if manager else None), login_name, _client_ip()))
        flash("Неверный логин или пароль.", "error")

    return render_template("login.html")


@bp.route("/login/2fa", methods=["GET", "POST"])
@rate_limit(max_calls=10, window_seconds=60)
def verify_2fa():
    manager_id = session.get("pending_2fa_manager_id")
    if not manager_id:
        return redirect(url_for("auth.login"))
    manager = query_one("SELECT * FROM managers WHERE id=? AND is_active=1", (manager_id,))
    if not manager or not manager["totp_enabled"]:
        session.pop("pending_2fa_manager_id", None)
        session.pop("pending_2fa_next", None)
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        code = request.form.get("code", "").strip().replace(" ", "")
        next_url = session.get("pending_2fa_next") or None

        if verify_totp(manager["totp_secret"], code):
            session.pop("pending_2fa_manager_id", None)
            session.pop("pending_2fa_next", None)
            _complete_login(manager)
            return redirect(next_url or url_for("dashboard.index"))

        if _try_consume_backup_code(manager, code):
            session.pop("pending_2fa_manager_id", None)
            session.pop("pending_2fa_next", None)
            _complete_login(manager)
            flash("Вход выполнен по резервному коду — он больше не действителен.", "success")
            return redirect(next_url or url_for("dashboard.index"))

        flash("Неверный код.", "error")

    return render_template("login_2fa.html")


@bp.route("/login/2fa/cancel")
def cancel_2fa():
    session.pop("pending_2fa_manager_id", None)
    session.pop("pending_2fa_next", None)
    return redirect(url_for("auth.login"))


def _close_work_session(manager_id):
    """Accrue elapsed time since session_started_at into total_seconds_worked
    and clear the marker. Safe to call even if no session was open."""
    m = query_one("SELECT session_started_at FROM managers WHERE id=?", (manager_id,))
    if m and m["session_started_at"]:
        execute(
            "UPDATE managers SET "
            "total_seconds_worked = total_seconds_worked + "
            "  CAST((julianday('now') - julianday(session_started_at)) * 86400 AS INTEGER), "
            "session_started_at = NULL "
            "WHERE id=?", (manager_id,))


@bp.route("/logout")
def logout():
    manager_id = session.get("manager_id")
    if manager_id:
        _close_work_session(manager_id)
        m = query_one("SELECT name FROM managers WHERE id=?", (manager_id,))
        log_activity(f"{m['name'] if m else manager_id} вышел из системы.", manager_id)
        session_uid = session.get("session_uid")
        if session_uid:
            execute("UPDATE active_sessions SET revoked=1 WHERE session_id=?", (session_uid,))
    session.clear()
    return redirect(url_for("auth.login"))
