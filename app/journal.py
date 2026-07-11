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

    manager_id = request.args.get("manager_id", type=int)
    search = request.args.get("q", "").strip()

    where, params = [], []
    if manager_id:
        where.append("a.manager_id = ?")
        params.append(manager_id)
    if search:
        where.append("a.message LIKE ?")
        params.append(f"%{search}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = query_all(
        f"SELECT a.*, m.name AS manager_name FROM activity a "
        f"LEFT JOIN managers m ON m.id = a.manager_id {where_sql} "
        f"ORDER BY a.id DESC LIMIT ? OFFSET ?",
        params + [PAGE_SIZE + 1, offset])
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    managers = query_all("SELECT id, name FROM managers ORDER BY name")

    return render_template("journal.html", entries=[dict(r) for r in rows],
                           page=page, has_more=has_more,
                           manager_id=manager_id, search=search,
                           managers=[dict(m) for m in managers])
