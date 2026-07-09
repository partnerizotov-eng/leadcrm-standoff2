"""Календарь событий — админ прописывает мероприятия/конкурсы/розыгрыши
на конкретные даты. Менеджеры видят месяц в виде сетки ячеек: прошедшие
и сегодняшний день можно открыть и посмотреть, что там; будущие дни
закрыты интригой до наступления даты. Если к дню привязан бонус голды —
каждый менеджер, открывший день, получает его один раз."""
import calendar as _pycalendar
from datetime import date, datetime

from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify

from . import db
from .db import execute, query_one, query_all
from .security import login_required, admin_required
from .notifications import notify

bp = Blueprint("advent_calendar", __name__, url_prefix="/calendar")

MONTH_NAMES_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


@bp.route("/")
@login_required
def index():
    manager_id = session["manager_id"]
    today = date.today()

    year = request.args.get("year", today.year, type=int)
    month = request.args.get("month", today.month, type=int)
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    days_in_month = _pycalendar.monthrange(year, month)[1]
    month_prefix = f"{year:04d}-{month:02d}-"

    events_rows = query_all(
        "SELECT * FROM calendar_events WHERE event_date LIKE ? ORDER BY event_date", (month_prefix + "%",))
    events_by_date = {e["event_date"]: dict(e) for e in events_rows}

    claims_rows = query_all(
        "SELECT event_id FROM calendar_claims WHERE manager_id=?", (manager_id,))
    claimed_event_ids = {c["event_id"] for c in claims_rows}

    days = []
    for d in range(1, days_in_month + 1):
        day_date = date(year, month, d)
        date_str = day_date.isoformat()
        event = events_by_date.get(date_str)
        days.append({
            "day": d,
            "date": date_str,
            "is_today": day_date == today,
            "is_past_or_today": day_date <= today,
            "has_event": event is not None,
            "event": event,
            "claimed": event["id"] in claimed_event_ids if event else False,
        })

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    return render_template("advent_calendar.html",
                          days=days,
                          month_name=MONTH_NAMES_RU[month],
                          year=year, month=month,
                          prev_month=prev_month, prev_year=prev_year,
                          next_month=next_month, next_year=next_year,
                          is_admin=(session.get("role") == "admin"),
                          today_iso=today.isoformat())


@bp.route("/day/<date_str>/open", methods=["POST"])
@login_required
def open_day(date_str):
    manager_id = session["manager_id"]
    try:
        day_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify(error="Некорректная дата"), 400

    if day_date > date.today():
        return jsonify(error="Этот день ещё не наступил"), 400

    event = query_one("SELECT * FROM calendar_events WHERE event_date=?", (date_str,))
    if not event:
        return jsonify(error="На этот день ничего не запланировано"), 404

    already_claimed = query_one(
        "SELECT id FROM calendar_claims WHERE event_id=? AND manager_id=?", (event["id"], manager_id))

    reward_granted = 0
    if event["reward_amount"] and not already_claimed:
        with db.transaction() as conn:
            conn.execute("UPDATE managers SET balance = balance + ?, total_earned = total_earned + ? WHERE id=?",
                        (event["reward_amount"], event["reward_amount"], manager_id))
            conn.execute("INSERT INTO manager_ledger (manager_id, amount, reason, reference_id) "
                        "VALUES (?, ?, 'calendar_reward', ?)", (manager_id, event["reward_amount"], event["id"]))
            conn.execute("INSERT INTO calendar_claims (event_id, manager_id) VALUES (?, ?)",
                        (event["id"], manager_id))
        reward_granted = event["reward_amount"]
    elif not already_claimed:
        execute("INSERT INTO calendar_claims (event_id, manager_id) VALUES (?, ?)", (event["id"], manager_id))

    return jsonify(
        title=event["title"],
        description=event["description"],
        icon=event["icon"],
        reward_granted=reward_granted,
        already_claimed=bool(already_claimed),
    )


# ==================== АДМИН: УПРАВЛЕНИЕ СОБЫТИЯМИ ====================

@bp.route("/admin")
@admin_required
def admin_index():
    events = query_all("SELECT * FROM calendar_events ORDER BY event_date DESC LIMIT 100")
    return render_template("advent_calendar_admin.html", events=[dict(e) for e in events])


@bp.route("/admin/create", methods=["POST"])
@admin_required
def admin_create():
    event_date = request.form.get("event_date", "").strip()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    icon = request.form.get("icon", "🎁").strip() or "🎁"
    reward_raw = request.form.get("reward_amount", "").strip()

    if not event_date or not title:
        flash("Укажите дату и заголовок события.", "error")
        return redirect(url_for("advent_calendar.admin_index"))

    reward_amount = None
    if reward_raw:
        try:
            reward_amount = float(reward_raw)
            if reward_amount <= 0:
                reward_amount = None
        except ValueError:
            reward_amount = None

    existing = query_one("SELECT id FROM calendar_events WHERE event_date=?", (event_date,))
    if existing:
        execute("""UPDATE calendar_events SET title=?, description=?, icon=?, reward_amount=?
                   WHERE event_date=?""", (title, description, icon, reward_amount, event_date))
        flash("✅ Событие на эту дату обновлено.", "success")
    else:
        execute("""INSERT INTO calendar_events (event_date, title, description, icon, reward_amount, created_by)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (event_date, title, description, icon, reward_amount, session["manager_id"]))
        flash("✅ Событие добавлено в календарь.", "success")

        try:
            event_dt = datetime.strptime(event_date, "%Y-%m-%d").date()
            if event_dt >= date.today():
                managers = query_all("SELECT id FROM managers WHERE role='manager'")
                for m in managers:
                    notify(m["id"], f"🗓️ В календаре появилось новое событие на {event_date}!", "/calendar")

                from .chatbot import announce_calendar_event
                announce_calendar_event(event_date, title)
        except ValueError:
            pass

    return redirect(url_for("advent_calendar.admin_index"))


@bp.route("/admin/<int:event_id>/delete", methods=["POST"])
@admin_required
def admin_delete(event_id):
    execute("DELETE FROM calendar_events WHERE id=?", (event_id,))
    flash("✅ Событие удалено.", "success")
    return redirect(url_for("advent_calendar.admin_index"))
