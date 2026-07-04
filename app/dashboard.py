from flask import Blueprint, render_template, session

from .db import query_all, query_one
from .leads import STATUS_LABELS, STATUSES
from .managers import manager_stats
from .security import login_required

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    manager_id, role = session["manager_id"], session["role"]
    pending_submissions = pending_withdrawals = total_balance_owed = None

    if role == "admin":
        funnel = {s: query_one("SELECT COUNT(*) c FROM leads WHERE status=?", (s,))["c"] for s in STATUSES}
        total = sum(funnel.values()) or 1

        pending_submissions = query_one("SELECT COUNT(*) c FROM submissions WHERE status='pending'")["c"]
        pending_withdrawals = query_one(
            "SELECT COUNT(*) c FROM withdrawals WHERE status IN ('awaiting_listing','proof_submitted')")["c"]
        total_balance_owed = query_one(
            "SELECT COALESCE(SUM(balance),0) v FROM managers WHERE role='manager'")["v"]

        leaderboard = query_all(
            "SELECT m.id, m.name, "
            "COUNT(l.id) total_leads, "
            "SUM(CASE WHEN l.status NOT IN ('new') THEN 1 ELSE 0 END) contacted, "
            "SUM(CASE WHEN l.status IN ('joined_channel','participated','returning') THEN 1 ELSE 0 END) converted, "
            "SUM(CASE WHEN l.status='returning' THEN 1 ELSE 0 END) returning_count "
            "FROM managers m LEFT JOIN leads l ON l.assigned_manager_id=m.id "
            "WHERE m.role='manager' GROUP BY m.id ORDER BY converted DESC")
        leaderboard = [dict(r) for r in leaderboard]
        for r in leaderboard:
            r["conversion_pct"] = round(r["converted"] / r["total_leads"] * 100) if r["total_leads"] else 0
        top3 = sorted(manager_stats(), key=lambda x: x["earnings"], reverse=True)[:3]

        my_leads = None
        my_stats = None
    else:
        funnel = {s: query_one("SELECT COUNT(*) c FROM leads WHERE status=? AND assigned_manager_id=?",
                               (s, manager_id))["c"] for s in STATUSES}
        total = sum(funnel.values()) or 1
        leaderboard = None
        top3 = None
        my_leads = query_one("SELECT COUNT(*) c FROM leads WHERE assigned_manager_id=? AND "
                             "status NOT IN ('declined','unresponsive','returning')", (manager_id,))["c"]
        my_stats = next((m for m in manager_stats() if m["id"] == manager_id), None)

    return render_template("dashboard.html", funnel=funnel, total=total, statuses=STATUSES,
                           status_labels=STATUS_LABELS, leaderboard=leaderboard, top3=top3,
                           my_leads=my_leads, my_stats=my_stats,
                           is_admin=(role == "admin"),
                           pending_submissions=pending_submissions,
                           pending_withdrawals=pending_withdrawals,
                           total_balance_owed=total_balance_owed)
