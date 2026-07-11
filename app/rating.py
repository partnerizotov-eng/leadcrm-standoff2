"""Рейтинг менеджеров по реальным бизнес-KPI (не игровым ачивкам):
конверсия, объём, заработок. Раньше был просто заглушкой, которая
возвращала сырой HTML-текст и даже не была подключена к приложению —
теперь настоящая страница, использующая уже готовый templates/rating.html.
"""
from flask import Blueprint, render_template, session

from .db import query_one
from .managers import manager_stats
from .security import login_required

bp = Blueprint("rating", __name__)


@bp.route("/rating/export.csv")
@login_required
def export_csv():
    managers = manager_stats()
    import csv
    import io
    from flask import Response
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Менеджер", "Лидов всего", "Одобрено заявок", "Конверсия %", "Баланс", "Заработано всего"])
    for m in managers:
        conv = round(m["processed_count"] / m["leads_total"] * 100) if m["leads_total"] else 0
        writer.writerow([m["name"], m["leads_total"], m["processed_count"], conv, m["balance"], m["total_earned"]])
    csv_data = "\ufeff" + buf.getvalue()
    return Response(csv_data, mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=rating_export.csv"
    })


@bp.route("/rating/seasons")
@login_required
def seasons():
    from .db import query_all
    rows = query_all("SELECT * FROM rating_seasons ORDER BY id DESC")
    import json as _json
    parsed = []
    for r in rows:
        d = dict(r)
        d["standings"] = _json.loads(d["standings"])
        parsed.append(d)
    return render_template("rating_seasons.html", seasons=parsed)


@bp.route("/rating/seasons/close", methods=["POST"])
@login_required
def close_season():
    if session.get("role") != "admin":
        from flask import flash, redirect, url_for as _url_for
        flash("Закрывать сезон может только админ.", "error")
        return redirect(_url_for("rating.index"))

    from flask import flash, redirect, request, url_for as _url_for
    import json as _json
    from .db import execute, query_one as _qo

    label = request.form.get("label", "").strip() or "Сезон"
    managers = manager_stats()
    standings = []
    for m in managers:
        conversion_pct = round(m["processed_count"] / m["leads_total"] * 100) if m["leads_total"] else 0
        standings.append({"name": m["name"], "total_leads": m["leads_total"],
                          "conversion_pct": conversion_pct, "total_earned": m["total_earned"]})
    standings.sort(key=lambda r: (r["conversion_pct"], r["total_leads"]), reverse=True)

    last = _qo("SELECT ended_at FROM rating_seasons ORDER BY id DESC LIMIT 1")
    started_at = last["ended_at"] if last else None

    execute("INSERT INTO rating_seasons (label, started_at, standings) VALUES (?, ?, ?)",
            (label, started_at, _json.dumps(standings, ensure_ascii=False)))
    flash(f"✅ Сезон «{label}» заархивирован — текущий рейтинг сохранён как снимок.", "success")
    return redirect(_url_for("rating.seasons"))


@bp.route("/rating")
@login_required
def index():
    managers = manager_stats()

    rating = []
    for m in managers:
        conversion_pct = round(m["processed_count"] / m["leads_total"] * 100) if m["leads_total"] else 0
        rating.append({
            "id": m["id"],
            "name": m["name"],
            "total_leads": m["leads_total"],
            "approved_submissions": m["processed_count"],
            "conversion_pct": conversion_pct,
            "balance": m["balance"],
            "total_earned": m["total_earned"],
        })
    rating.sort(key=lambda r: (r["conversion_pct"], r["total_leads"]), reverse=True)

    total_leads = query_one("SELECT COUNT(*) c FROM leads")["c"]
    total_participations = query_one(
        "SELECT COUNT(*) c FROM leads WHERE status IN ('participated','returning')")["c"]
    total_balance = query_one("SELECT COALESCE(SUM(balance),0) v FROM managers WHERE role='manager'")["v"]
    total_debt = query_one("SELECT COALESCE(SUM(balance),0) v FROM leads")["v"]

    stats = {
        "total_leads": total_leads,
        "total_managers": len(rating),
        "total_participations": total_participations,
        "avg_conversion": round(total_participations / total_leads * 100) if total_leads else 0,
        "total_balance": total_balance,
        "total_debt": total_debt,
    }

    my_id = session.get("manager_id")
    current_pos = next((i + 1 for i, r in enumerate(rating) if r["id"] == my_id), None)

    return render_template("rating.html", rating=rating, stats=stats, current_pos=current_pos)
