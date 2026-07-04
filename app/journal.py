"""Journal — a single, read-only feed of everything that happened: manager
account changes, submission decisions, withdrawal decisions, balance
corrections, commission changes, logins/logouts. Admin-only."""
from flask import Blueprint, render_template, request

from .db import query_all
from .security import admin_required

bp = Blueprint("journal", __name__)

PAGE_SIZE = 100


@bp.route("/journal")
@admin_required
def index():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    offset = (page - 1) * PAGE_SIZE

    rows = query_all(
        "SELECT a.*, m.name AS manager_name FROM activity a "
        "LEFT JOIN managers m ON m.id = a.manager_id "
        "ORDER BY a.id DESC LIMIT ? OFFSET ?", (PAGE_SIZE + 1, offset))
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    return render_template("journal.html", entries=[dict(r) for r in rows],
                           page=page, has_more=has_more)
