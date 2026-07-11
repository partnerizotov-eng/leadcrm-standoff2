import json
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from .db import execute, query_all, query_one
from .leads import STATUS_LABELS, STATUSES
from .managers import manager_stats
from .security import login_required
from .contest import get_active_contest_summary

bp = Blueprint("dashboard", __name__)

STATUS_COLORS = {
    "new": "8A90A2", "contacted": "E9B949", "replied": "6C8CFF",
    "joined_channel": "45C4B0", "participated": "3ECF8E", "returning": "FFD700",
    "declined": "E56B6B", "unresponsive": "E56B6B",
}


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
        total_debt = query_one("SELECT COALESCE(SUM(balance),0) v FROM leads")["v"]

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
        contest_summary = get_active_contest_summary()
    else:
        funnel = {s: query_one("SELECT COUNT(*) c FROM leads WHERE status=? AND assigned_manager_id=?",
                               (s, manager_id))["c"] for s in STATUSES}
        total = sum(funnel.values()) or 1
        leaderboard = None
        top3 = None
        my_leads = query_one("SELECT COUNT(*) c FROM leads WHERE assigned_manager_id=? AND "
                             "status NOT IN ('declined','unresponsive','returning')", (manager_id,))["c"]
        my_stats = next((m for m in manager_stats() if m["id"] == manager_id), None)
        total_debt = None
        contest_summary = get_active_contest_summary()

    return render_template("dashboard.html", funnel=funnel, total=total, statuses=STATUSES,
                           status_labels=STATUS_LABELS, status_colors=STATUS_COLORS,
                           leaderboard=leaderboard, top3=top3,
                           my_leads=my_leads, my_stats=my_stats,
                           is_admin=(role == "admin"),
                           pending_submissions=pending_submissions,
                           pending_withdrawals=pending_withdrawals,
                           total_balance_owed=total_balance_owed,
                           total_debt=total_debt,
                           contest_summary=contest_summary,
                           widgets=_get_widget_prefs(session["manager_id"]))


@bp.route("/api/v1/stats")
@login_required
def api_stats():
    """Реальные данные для графика «Динамика активности» — раньше фронт
    дёргал этот путь, но маршрута не существовало вообще (404), и график
    молча показывал захардкоженные заглушечные числа. Возвращает число
    новых лидов по дням за последние 7 дней (для не-админа — только его)."""
    role = session["role"]
    manager_id = session["manager_id"]
    where = "" if role == "admin" else "AND assigned_manager_id=?"
    params = () if role == "admin" else (manager_id,)

    rows = query_all(f"""
        SELECT date(found_at) d, COUNT(*) c FROM leads
        WHERE found_at >= date('now', '-6 days') {where}
        GROUP BY date(found_at)
    """, params)
    by_day = {r["d"]: r["c"] for r in rows}

    labels, values = [], []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        labels.append((datetime.now() - timedelta(days=i)).strftime("%d.%m"))
        values.append(by_day.get(d, 0))

    return jsonify(labels=labels, values=values)


def _get_widget_prefs(manager_id):
    """Какие KPI-виджеты на дашборде показывать — хранится в
    manager_settings (key='dashboard_widgets', value=JSON-список видимых)."""
    row = query_one("SELECT value FROM manager_settings WHERE manager_id=? AND key='dashboard_widgets'",
                     (manager_id,))
    if not row or not row["value"]:
        return {"funnel": True, "leaderboard": True, "activity_chart": True}
    try:
        saved = json.loads(row["value"])
    except (ValueError, TypeError):
        saved = {}
    defaults = {"funnel": True, "leaderboard": True, "activity_chart": True}
    defaults.update(saved)
    return defaults


@bp.route("/dashboard/widgets", methods=["POST"])
@login_required
def save_widget_prefs():
    prefs = {
        "funnel": request.form.get("w_funnel") == "1",
        "leaderboard": request.form.get("w_leaderboard") == "1",
        "activity_chart": request.form.get("w_activity_chart") == "1",
    }
    execute(
        "INSERT INTO manager_settings (manager_id, key, value) VALUES (?, 'dashboard_widgets', ?) "
        "ON CONFLICT(manager_id, key) DO UPDATE SET value=excluded.value",
        (session["manager_id"], json.dumps(prefs)))
    flash("Настройки дашборда сохранены.", "success")
    return redirect(url_for("dashboard.index"))
