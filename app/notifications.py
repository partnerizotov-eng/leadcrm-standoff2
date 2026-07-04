from flask import Blueprint, jsonify, redirect, render_template, session, url_for

from .db import execute, query_all, query_one
from .security import login_required

bp = Blueprint("notifications", __name__)


def notify(manager_id, message, link=""):
    execute("INSERT INTO notifications (manager_id, message, link) VALUES (?, ?, ?)",
            (manager_id, message, link))


def notify_all_admins(message, link=""):
    for admin in query_all("SELECT id FROM managers WHERE role='admin'"):
        notify(admin["id"], message, link)


@bp.route("/notifications")
@login_required
def index():
    """Страница уведомлений"""
    rows = query_all("SELECT * FROM notifications WHERE manager_id=? ORDER BY id DESC LIMIT 100",
                     (session["manager_id"],))
    return render_template("notifications.html", notifications=[dict(r) for r in rows])


@bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@login_required
def mark_read(notif_id):
    row = query_one("SELECT manager_id, link FROM notifications WHERE id=?", (notif_id,))
    if not row or row["manager_id"] != session["manager_id"]:
        return redirect(url_for("dashboard.index"))
    execute("UPDATE notifications SET is_read=1 WHERE id=?", (notif_id,))
    return redirect(row["link"] or url_for("dashboard.index"))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    execute("UPDATE notifications SET is_read=1 WHERE manager_id=?", (session["manager_id"],))
    return redirect(url_for("notifications.index"))