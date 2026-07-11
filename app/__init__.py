from datetime import timedelta

from flask import Flask, jsonify, render_template, request, session, redirect, url_for

from config import Config
from . import db
from .security import csrf_field, csrf_protect, csrf_token


def create_app(config_object=Config):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(config_object)
    app.permanent_session_lifetime = timedelta(hours=app.config["SESSION_LIFETIME_HOURS"])

    if app.config.get("ENV") == "production" and app.config.get("SECRET_KEY") == "change-me-in-production":
        raise RuntimeError("Refusing to start in production with the default SECRET_KEY.")

    app.teardown_appcontext(db.close_db)
    
    with app.app_context():
        db.init_db()
        db.ensure_admin()

    app.before_request(csrf_protect)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["csrf_field"] = csrf_field

    def unread_chat_count():
        manager_id = session.get("manager_id")
        if not manager_id:
            return 0
        from .db import query_one as _qo
        state = _qo("SELECT last_read_id FROM chat_read_state WHERE manager_id=?", (manager_id,))
        last_read_id = state["last_read_id"] if state else 0
        row = _qo("SELECT COUNT(*) c FROM chat_messages WHERE id > ? AND manager_id != ?", (last_read_id, manager_id))
        return row["c"] if row else 0
    app.jinja_env.globals["unread_chat_count"] = unread_chat_count

    from .tours import get_active_tour, get_tour_for_replay
    app.jinja_env.globals["get_active_tour"] = get_active_tour
    app.jinja_env.globals["get_tour_for_replay"] = get_tour_for_replay

    def unread_notifications_count():
        manager_id = session.get("manager_id")
        if not manager_id:
            return 0
        from .db import query_one as _qo
        row = _qo("SELECT COUNT(*) c FROM notifications WHERE manager_id=? AND is_read=0", (manager_id,))
        return row["c"] if row else 0
    app.jinja_env.globals["unread_notifications_count"] = unread_notifications_count

    @app.before_request
    def force_profile_completion():
        if not request.endpoint or request.endpoint == "static":
            return
        if request.endpoint.startswith(("auth.", "profile.", "uploads.")):
            return
        manager_id = session.get("manager_id")
        if not manager_id:
            return
        manager = db.query_one("SELECT profile_completed FROM managers WHERE id=? AND is_deleted=0", (manager_id,))
        if not manager:
            # Сессия ссылается на менеджера, которого в текущей базе больше
            # нет (база была очищена/восстановлена из бэкапа, менеджер
            # удалён) — выходим из мёртвой сессии. Без этой проверки код
            # ниже по цепочке падает с 500 (FOREIGN KEY constraint failed)
            # там, где несуществующий manager_id используется как FK.
            session.clear()
            return redirect(url_for("auth.login"))

        session_uid = session.get("session_uid")
        if session_uid:
            sess_row = db.query_one("SELECT revoked FROM active_sessions WHERE session_id=?", (session_uid,))
            if sess_row and sess_row["revoked"]:
                # Админ принудительно разлогинил эту сессию со страницы
                # "Активные сессии" — сразу выходим, даже если это сессия
                # самого админа.
                session.clear()
                return redirect(url_for("auth.login"))
            db.execute("UPDATE active_sessions SET last_seen_at=datetime('now') WHERE session_id=?", (session_uid,))

        if request.endpoint.startswith(("admin.", "funnel.", "risk.")) or request.endpoint == "managers.index":
            allowlist = db.query_all("SELECT ip_or_cidr FROM admin_ip_allowlist")
            if allowlist:
                from .security import ip_allowed
                ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
                if not ip_allowed(ip, [r["ip_or_cidr"] for r in allowlist]):
                    return "Доступ запрещён с этого IP-адреса.", 403

        if session.get("role") == "admin":
            return
        if not manager["profile_completed"]:
            return redirect(url_for("profile.complete"))

    from .leads import vk_chat_url
    app.jinja_env.globals["vk_chat_url"] = vk_chat_url

    import json as _json_mod
    app.jinja_env.filters["from_json"] = lambda s: _json_mod.loads(s) if s else []

    from .pii_encryption import decrypt_field
    app.jinja_env.filters["decrypt_pii"] = decrypt_field

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    @app.context_processor
    def inject_globals():
        manager = None
        if session.get("manager_id"):
            manager = db.query_one("SELECT * FROM managers WHERE id=?", (session["manager_id"],))
        return {"current_manager": dict(manager) if manager else None, "app_name": app.config["APP_NAME"]}

    from .auth import bp as auth_bp
    from .leads import bp as leads_bp
    from .scripts import bp as scripts_bp
    from .dashboard import bp as dashboard_bp
    from .managers import bp as managers_bp
    from .submissions import bp as submissions_bp
    from .withdrawals import bp as withdrawals_bp
    from .notifications import bp as notifications_bp
    from .uploads import bp as uploads_bp
    from .journal import bp as journal_bp
    from .game import bp as game_bp
    from .achievements import bp as achievements_bp
    from .referrals import bp as referrals_bp
    from .ai_assistant import bp as ai_bp
    from .admin_panel import admin_bp
    from .payouts import bp as payouts_bp
    from .support_tickets import bp as support_tickets_bp
    from .profile import bp as profile_bp
    from .contest import bp as contest_bp
    from .chat import bp as chat_bp
    from .wheel import bp as wheel_bp
    from .tours import bp as tours_bp
    from .advent_calendar import bp as advent_calendar_bp
    from .db_export import bp as db_export_bp
    from .puzzle import bp as puzzle_bp
    from .simulator import bp as simulator_bp
    from .rating import bp as rating_bp
    from .funnel import bp as funnel_bp
    from .risk_dashboard import bp as risk_bp
    from .totp_setup import bp as totp_setup_bp
    from .push_notify import bp as push_bp
    from .team import bp as team_bp

    for bp in (auth_bp, leads_bp, scripts_bp, dashboard_bp, managers_bp,
               submissions_bp, withdrawals_bp, notifications_bp, uploads_bp,
               journal_bp, game_bp, achievements_bp, referrals_bp, ai_bp,
               admin_bp, payouts_bp, support_tickets_bp, profile_bp,
               contest_bp, chat_bp, db_export_bp, wheel_bp, advent_calendar_bp,
               puzzle_bp, simulator_bp, rating_bp, funnel_bp, risk_bp, totp_setup_bp, push_bp, team_bp):
        app.register_blueprint(bp)

    from .backup_scheduler import start_backup_scheduler
    start_backup_scheduler(app)

    from .telegram_notify import start_risk_digest_scheduler
    start_risk_digest_scheduler(app)

    from .wheel import ensure_wheel_prizes
    with app.app_context():
        ensure_wheel_prizes()

    from .chatbot import ensure_bot_account, start_daily_summary_scheduler
    with app.app_context():
        ensure_bot_account()
    start_daily_summary_scheduler(app)
    
    @app.context_processor
    def inject_notifications():
        if not session.get("manager_id"):
            return {}
        unread = db.query_one("SELECT COUNT(*) c FROM notifications WHERE manager_id=? AND is_read=0",
                              (session["manager_id"],))
        return {"unread_notifications": unread["c"] if unread else 0}

    @app.errorhandler(403)
    def forbidden(_e):
        if request.path.startswith("/api/"):
            return jsonify(error="Forbidden"), 403
        return render_template("error.html", code=403, message="Доступ запрещён."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="Страница не найдена."), 404

    @app.errorhandler(429)
    def too_many(_e):
        return render_template("error.html", code=429, message="Слишком много попыток. Подождите."), 429

    @app.route("/healthz")
    def healthz():
        try:
            db.query_one("SELECT 1 v")
        except Exception:
            return jsonify(status="error"), 503
        return jsonify(status="ok")

    @app.route("/health")
    def health():
        from flask import jsonify
        try:
            db.query_one("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
        status = 200 if db_ok else 503
        return jsonify(status="ok" if db_ok else "error", database=db_ok), status

    return app


# ---------------------------------------------------------------------------
# Module-level WSGI singletons.
#
# Building the application here (once, at import time) means EVERY common
# server target resolves to the same working app, no matter how the host is
# configured:
#   gunicorn app:app            gunicorn app:application
#   gunicorn wsgi:app           gunicorn wsgi:application
#   gunicorn run:app            Passenger  -> passenger_wsgi:application
# ---------------------------------------------------------------------------
app = create_app()
application = app
