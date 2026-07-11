from flask import Blueprint, flash, redirect, render_template, url_for

from .risk_scoring import compute_risk_report
from .security import admin_required
from .telegram_notify import is_telegram_configured, send_telegram_message, format_risk_digest

bp = Blueprint("risk", __name__, url_prefix="/admin")


@bp.route("/risk")
@admin_required
def index():
    report = compute_risk_report()
    return render_template("risk.html", report=report, telegram_configured=is_telegram_configured())


@bp.route("/risk/send-telegram", methods=["POST"])
@admin_required
def send_telegram():
    if not is_telegram_configured():
        flash("Telegram не настроен — задай TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env.", "error")
        return redirect(url_for("risk.index"))
    report = compute_risk_report()
    ok = send_telegram_message(format_risk_digest(report))
    flash("✅ Отправлено в Telegram." if ok else "❌ Не удалось отправить — проверь токен/chat_id и сеть.",
          "success" if ok else "error")
    return redirect(url_for("risk.index"))
