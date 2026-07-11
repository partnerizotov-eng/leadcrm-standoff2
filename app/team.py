"""Команда: календарь смен, отчёт по отработанным часам, штрафы/бонусы
с обязательной причиной (для аудита), и роль тимлида."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .db import execute, query_all, query_one
from .managers import _fmt_hours
from .security import admin_required, login_required

bp = Blueprint("team", __name__, url_prefix="/team")


# ==================== Календарь смен ====================

@bp.route("/shifts")
@login_required
def shifts():
    role, manager_id = session["role"], session["manager_id"]
    month = request.args.get("month", "")  # YYYY-MM
    if not month:
        from datetime import datetime
        month = datetime.now().strftime("%Y-%m")

    if role == "admin":
        rows = query_all(
            "SELECT s.*, m.name manager_name FROM shifts s JOIN managers m ON m.id=s.manager_id "
            "WHERE strftime('%Y-%m', s.shift_date) = ? ORDER BY s.shift_date, s.start_time", (month,))
    else:
        rows = query_all(
            "SELECT s.*, m.name manager_name FROM shifts s JOIN managers m ON m.id=s.manager_id "
            "WHERE s.manager_id=? AND strftime('%Y-%m', s.shift_date) = ? ORDER BY s.shift_date, s.start_time",
            (manager_id, month))

    managers = query_all("SELECT id, name FROM managers WHERE role='manager' ORDER BY name")
    return render_template("shifts.html", shifts=[dict(r) for r in rows], month=month,
                           managers=[dict(m) for m in managers], is_admin=(role == "admin"))


@bp.route("/shifts/add", methods=["POST"])
@admin_required
def shifts_add():
    manager_id = request.form.get("manager_id", type=int)
    shift_date = request.form.get("shift_date", "").strip()
    start_time = request.form.get("start_time", "").strip()
    end_time = request.form.get("end_time", "").strip()
    if not (manager_id and shift_date and start_time and end_time):
        flash("Заполни все поля смены.", "error")
        return redirect(url_for("team.shifts"))
    execute("INSERT INTO shifts (manager_id, shift_date, start_time, end_time, created_by) VALUES (?,?,?,?,?)",
            (manager_id, shift_date, start_time, end_time, session["manager_id"]))
    flash("✅ Смена добавлена.", "success")
    return redirect(url_for("team.shifts", month=shift_date[:7]))


@bp.route("/shifts/<int:shift_id>/delete", methods=["POST"])
@admin_required
def shifts_delete(shift_id):
    execute("DELETE FROM shifts WHERE id=?", (shift_id,))
    flash("Смена удалена.", "success")
    return redirect(url_for("team.shifts"))


# ==================== Отчёт по отработанным часам ====================

@bp.route("/hours")
@admin_required
def hours_report():
    rows = query_all("""
        SELECT id, name,
          total_seconds_worked +
          COALESCE(CAST((julianday('now') - julianday(session_started_at)) * 86400 AS INTEGER), 0) AS live_seconds
        FROM managers WHERE role='manager' ORDER BY live_seconds DESC
    """)
    report = [{"id": r["id"], "name": r["name"], "seconds": r["live_seconds"],
               "label": _fmt_hours(r["live_seconds"])} for r in rows]
    return render_template("hours_report.html", report=report)


# ==================== Штрафы / бонусы (с обязательной причиной) ====================

@bp.route("/adjustments")
@admin_required
def adjustments():
    rows = query_all("""
        SELECT a.*, m.name manager_name, ad.name admin_name
        FROM balance_adjustments a
        JOIN managers m ON m.id = a.manager_id
        LEFT JOIN managers ad ON ad.id = a.admin_id
        ORDER BY a.id DESC LIMIT 200
    """)
    managers = query_all("SELECT id, name FROM managers WHERE role='manager' ORDER BY name")
    return render_template("adjustments.html", rows=[dict(r) for r in rows],
                           managers=[dict(m) for m in managers])


@bp.route("/adjustments/add", methods=["POST"])
@admin_required
def adjustments_add():
    manager_id = request.form.get("manager_id", type=int)
    kind = request.form.get("kind", "other")
    reason = request.form.get("reason", "").strip()
    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0

    if not manager_id or not amount or not reason:
        flash("Сумма и причина обязательны — без них корректировку не проведём.", "error")
        return redirect(url_for("team.adjustments"))

    manager = query_one("SELECT balance FROM managers WHERE id=?", (manager_id,))
    if not manager:
        flash("Менеджер не найден.", "error")
        return redirect(url_for("team.adjustments"))

    before = manager["balance"]
    after = before + amount
    execute("UPDATE managers SET balance=? WHERE id=?", (after, manager_id))
    execute(
        "INSERT INTO balance_adjustments (manager_id, admin_id, amount, kind, reason, balance_before, balance_after) "
        "VALUES (?,?,?,?,?,?,?)",
        (manager_id, session["manager_id"], amount, kind, reason, before, after))

    from .db import log_activity
    log_activity(
        f"{'Бонус' if amount > 0 else 'Штраф'} менеджеру #{manager_id}: {amount:+.2f}G "
        f"(было {before:.2f}G → стало {after:.2f}G) — причина: {reason}", session["manager_id"])

    flash(f"✅ Корректировка проведена: {amount:+.2f}G.", "success")
    return redirect(url_for("team.adjustments"))
