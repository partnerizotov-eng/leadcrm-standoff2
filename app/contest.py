"""Конкурс менеджеров — глобальный зачёт по одобренным заявкам за период."""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from . import db
from .db import execute, query_one, query_all
from .security import admin_required, login_required
from .notifications import notify

bp = Blueprint("contest", __name__, url_prefix="/contest")

DEFAULT_PRIZES = [
    (1, 1, 1000), (2, 2, 500), (3, 3, 300), (4, 4, 200), (5, 9, 100),
]


def _current_contest():
    return query_one("SELECT * FROM contests WHERE is_active=1 ORDER BY id DESC LIMIT 1")


def _auto_create_default_contest():
    """Если активного конкурса нет — создаём его сразу с параметрами по
    умолчанию: старт сегодня в 14:00, финиш 31 июля. Не требует действий
    администратора."""
    from datetime import datetime
    now = datetime.now()
    start = now.replace(hour=14, minute=0, second=0, microsecond=0)
    end = datetime(now.year, 7, 31, 23, 59, 0)
    if end < now:
        end = datetime(now.year + 1, 7, 31, 23, 59, 0)

    contest_id = execute("INSERT INTO contests (title, starts_at, ends_at) VALUES (?, ?, ?)",
                         ("Летний конкурс менеджеров",
                          start.strftime("%Y-%m-%dT%H:%M:%S"),
                          end.strftime("%Y-%m-%dT%H:%M:%S")))
    for place_from, place_to, amount in DEFAULT_PRIZES:
        execute("INSERT INTO contest_prizes (contest_id, place_from, place_to, amount) VALUES (?, ?, ?, ?)",
                (contest_id, place_from, place_to, amount))
    return query_one("SELECT * FROM contests WHERE id=?", (contest_id,))


def _leaderboard(contest, limit=None):
    sql = """
        SELECT m.id as manager_id, m.name, COUNT(s.id) as approved_count
        FROM submissions s
        JOIN managers m ON m.id = s.manager_id
        WHERE s.status='approved' AND s.reviewed_at >= ? AND s.reviewed_at <= ?
        GROUP BY m.id
        ORDER BY approved_count DESC, m.id ASC
    """
    rows = query_all(sql, (contest["starts_at"], contest["ends_at"]))
    rows = [dict(r) for r in rows]
    if limit:
        rows = rows[:limit]
    return rows


def _prize_for_place(contest_id, place):
    prizes = query_all("SELECT * FROM contest_prizes WHERE contest_id=?", (contest_id,))
    for p in prizes:
        if p["place_from"] <= place <= p["place_to"]:
            return p["amount"]
    return 0


def _parse_dt(s):
    from datetime import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.now()


@bp.route("/")
@login_required
def index():
    from datetime import datetime
    contest = _current_contest()
    if not contest:
        contest = _auto_create_default_contest()

    leaderboard = []
    winners = []
    phase = None

    if contest:
        if contest["prizes_paid"]:
            phase = "finished"
            winners = query_all("SELECT cw.*, m.name FROM contest_winners cw JOIN managers m ON m.id=cw.manager_id "
                               "WHERE cw.contest_id=? ORDER BY cw.place ASC", (contest["id"],))
        else:
            now = datetime.now()
            starts = _parse_dt(contest["starts_at"])
            ends = _parse_dt(contest["ends_at"])
            if now < starts:
                phase = "upcoming"
            elif now <= ends:
                phase = "active"
            else:
                phase = "awaiting_finish"
            leaderboard = _leaderboard(contest, limit=20)

    return render_template("contest.html",
                          contest=dict(contest) if contest else None,
                          leaderboard=leaderboard,
                          winners=[dict(w) for w in winners],
                          phase=phase,
                          is_admin=(session.get("role") == "admin"),
                          my_manager_id=session.get("manager_id"))


@bp.route("/create", methods=["POST"])
@admin_required
def create():
    title = request.form.get("title", "").strip() or "Конкурс менеджеров"
    starts_at = request.form.get("starts_at", "").strip()
    ends_at = request.form.get("ends_at", "").strip()

    if not starts_at or not ends_at:
        flash("Укажите даты начала и окончания.", "error")
        return redirect(url_for("contest.index"))

    execute("UPDATE contests SET is_active=0 WHERE is_active=1")

    contest_id = execute("""INSERT INTO contests (title, starts_at, ends_at, created_by)
                           VALUES (?, ?, ?, ?)""", (title, starts_at, ends_at, session["manager_id"]))

    for place_from, place_to, amount in DEFAULT_PRIZES:
        execute("""INSERT INTO contest_prizes (contest_id, place_from, place_to, amount)
                   VALUES (?, ?, ?, ?)""", (contest_id, place_from, place_to, amount))

    managers = query_all("SELECT id FROM managers WHERE role='manager'")
    for m in managers:
        notify(m["id"], f"🏆 Стартует конкурс «{title}»! Собирай одобренные заявки и попади в топ-9.", "/contest")

    flash("✅ Конкурс создан.", "success")
    return redirect(url_for("contest.index"))


@bp.route("/finish", methods=["POST"])
@admin_required
def finish():
    contest = _current_contest()
    if not contest:
        flash("Активного конкурса нет.", "error")
        return redirect(url_for("contest.index"))
    if contest["prizes_paid"]:
        flash("Призы уже начислены ранее.", "error")
        return redirect(url_for("contest.index"))

    leaderboard = _leaderboard(contest)
    admin_id = session["manager_id"]

    with db.transaction() as conn:
        for idx, row in enumerate(leaderboard[:9]):
            place = idx + 1
            amount = _prize_for_place(contest["id"], place)
            if amount <= 0:
                continue
            conn.execute("UPDATE managers SET balance = balance + ?, total_earned = total_earned + ? WHERE id=?",
                        (amount, amount, row["manager_id"]))
            conn.execute("""INSERT INTO manager_ledger (manager_id, amount, reason, reference_id, actor_manager_id)
                           VALUES (?, ?, 'contest_prize', ?, ?)""",
                        (row["manager_id"], amount, contest["id"], admin_id))
            conn.execute("""INSERT INTO contest_winners (contest_id, manager_id, place, approved_count, amount)
                           VALUES (?, ?, ?, ?, ?)""",
                        (contest["id"], row["manager_id"], place, row["approved_count"], amount))
        conn.execute("UPDATE contests SET prizes_paid=1, is_active=0 WHERE id=?", (contest["id"],))

    for idx, row in enumerate(leaderboard[:9]):
        amount = _prize_for_place(contest["id"], idx + 1)
        if amount > 0:
            notify(row["manager_id"], f"🏆 Конкурс завершён! Твоё место: {idx+1}. Начислено {amount:.0f}G!", "/contest")

    flash("✅ Призы начислены, конкурс завершён.", "success")
    return redirect(url_for("contest.index"))
