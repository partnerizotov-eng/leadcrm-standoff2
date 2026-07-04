from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .db import execute, log_activity, query_one
from .security import rate_limit, verify_password

bp = Blueprint("auth", __name__)


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
            session.clear()
            session.permanent = True
            session["manager_id"] = manager["id"]
            session["role"] = manager["role"]
            session["name"] = manager["name"]
            # Start a work-time session — accrued on logout (or on the next
            # login, if the browser was just closed without logging out).
            execute("UPDATE managers SET session_started_at=datetime('now') WHERE id=?", (manager["id"],))
            log_activity(f"{manager['name']} вошёл в систему.", manager["id"])
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("Неверный логин или пароль.", "error")

    return render_template("login.html")


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
    session.clear()
    return redirect(url_for("auth.login"))
