from datetime import timedelta

from flask import Flask, jsonify, render_template, request, session

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

    from .leads import vk_chat_url
    app.jinja_env.globals["vk_chat_url"] = vk_chat_url

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

    for bp in (auth_bp, leads_bp, scripts_bp, dashboard_bp, managers_bp,
               submissions_bp, withdrawals_bp, notifications_bp, uploads_bp,
               journal_bp, game_bp, achievements_bp, referrals_bp, ai_bp):
        app.register_blueprint(bp)
    
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
