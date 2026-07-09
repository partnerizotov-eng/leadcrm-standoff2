"""Колесо призов. Менеджер получает одно вращение за каждые 3 одобренные
заявки. Администратор настраивает список призов, их суммы и веса
(вероятность выпадения) в админ-панели."""
import random

from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify

from . import db
from .db import execute, query_one, query_all
from .security import login_required, admin_required
from .notifications import notify

bp = Blueprint("wheel", __name__, url_prefix="/wheel")

APPROVALS_PER_SPIN = 3

DEFAULT_PRIZES = [
    ("10G", 10, 30, "#8A90A2"),
    ("20G", 20, 25, "#6C8CFF"),
    ("30G", 30, 20, "#3ECF8E"),
    ("50G", 50, 15, "#E9B949"),
    ("100G", 100, 7, "#FFD700"),
    ("200G", 200, 3, "#E56B6B"),
]


def ensure_wheel_prizes():
    """Засеивает призы по умолчанию один раз, если таблица пуста."""
    existing = query_one("SELECT COUNT(*) c FROM wheel_prizes")
    if existing and existing["c"] > 0:
        return
    for label, amount, weight, color in DEFAULT_PRIZES:
        execute("INSERT INTO wheel_prizes (label, amount, weight, color) VALUES (?, ?, ?, ?)",
                (label, amount, weight, color))


def grant_spin_on_approval(manager_id):
    """Вызывать сразу после одобрения заявки менеджера. Каждая APPROVALS_PER_SPIN-я
    одобренная заявка (по общему счёту, не сбрасываемому) даёт одно новое вращение."""
    total_approved = query_one(
        "SELECT COUNT(*) c FROM submissions WHERE manager_id=? AND status='approved'", (manager_id,))["c"]
    if total_approved > 0 and total_approved % APPROVALS_PER_SPIN == 0:
        execute("UPDATE managers SET wheel_spins_available = wheel_spins_available + 1 WHERE id=?", (manager_id,))
        notify(manager_id, "🎡 Новое вращение колеса призов доступно! Загляни в раздел «Колесо призов».",
               url_for("wheel.index"))


def _active_prizes():
    return query_all("SELECT * FROM wheel_prizes WHERE is_active=1 ORDER BY amount ASC")


@bp.route("/")
@login_required
def index():
    manager_id = session["manager_id"]
    me = query_one("SELECT wheel_spins_available FROM managers WHERE id=?", (manager_id,))
    prizes = [dict(p) for p in _active_prizes()]
    total_weight = sum(p["weight"] for p in prizes) or 1

    history = query_all(
        "SELECT * FROM wheel_spins WHERE manager_id=? ORDER BY id DESC LIMIT 20", (manager_id,))

    total_approved = query_one(
        "SELECT COUNT(*) c FROM submissions WHERE manager_id=? AND status='approved'", (manager_id,))["c"]
    progress_in_cycle = total_approved % APPROVALS_PER_SPIN

    return render_template("wheel.html",
                          spins_available=me["wheel_spins_available"] if me else 0,
                          prizes=prizes,
                          total_weight=total_weight,
                          history=[dict(h) for h in history],
                          progress_in_cycle=progress_in_cycle,
                          approvals_per_spin=APPROVALS_PER_SPIN,
                          is_admin=(session.get("role") == "admin"))


@bp.route("/spin", methods=["POST"])
@login_required
def spin():
    manager_id = session["manager_id"]
    manager = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))

    if not manager or manager["wheel_spins_available"] <= 0:
        return jsonify(error="Нет доступных вращений"), 400

    prizes = [dict(p) for p in _active_prizes()]
    if not prizes:
        return jsonify(error="Администратор ещё не настроил призы"), 400

    weights = [p["weight"] for p in prizes]
    chosen = random.choices(prizes, weights=weights, k=1)[0]
    prize_index = next(i for i, p in enumerate(prizes) if p["id"] == chosen["id"])

    with db.transaction() as conn:
        conn.execute("UPDATE managers SET wheel_spins_available = wheel_spins_available - 1, "
                    "balance = balance + ?, total_earned = total_earned + ? WHERE id=?",
                    (chosen["amount"], chosen["amount"], manager_id))
        conn.execute("INSERT INTO manager_ledger (manager_id, amount, reason, reference_id) "
                    "VALUES (?, ?, 'wheel_prize', ?)",
                    (manager_id, chosen["amount"], chosen["id"]))
        conn.execute("INSERT INTO wheel_spins (manager_id, prize_id, label, amount) VALUES (?, ?, ?, ?)",
                    (manager_id, chosen["id"], chosen["label"], chosen["amount"]))

    if chosen["amount"] >= 100:
        from .chatbot import announce_wheel_big_prize
        announce_wheel_big_prize(manager["name"], chosen["label"])

    return jsonify(
        prize_index=prize_index,
        label=chosen["label"],
        amount=chosen["amount"],
        spins_left=manager["wheel_spins_available"] - 1,
    )


# ==================== АДМИН: УПРАВЛЕНИЕ ПРИЗАМИ ====================

@bp.route("/admin/prizes")
@admin_required
def admin_prizes():
    prizes = query_all("SELECT * FROM wheel_prizes ORDER BY amount ASC")
    total_weight = sum(p["weight"] for p in prizes) or 1
    managers = query_all("SELECT id, name, wheel_spins_available FROM managers WHERE role='manager' ORDER BY name")
    return render_template("wheel_admin.html",
                          prizes=[dict(p) for p in prizes],
                          total_weight=total_weight,
                          managers=[dict(m) for m in managers])


@bp.route("/admin/prizes/create", methods=["POST"])
@admin_required
def admin_prizes_create():
    label = request.form.get("label", "").strip()
    try:
        amount = float(request.form.get("amount", 0))
        weight = int(request.form.get("weight", 10))
    except ValueError:
        flash("Некорректные числа.", "error")
        return redirect(url_for("wheel.admin_prizes"))

    color = request.form.get("color", "#6C8CFF").strip() or "#6C8CFF"

    if not label or amount <= 0 or weight <= 0:
        flash("Заполните все поля корректно (сумма и вес больше нуля).", "error")
        return redirect(url_for("wheel.admin_prizes"))

    execute("INSERT INTO wheel_prizes (label, amount, weight, color) VALUES (?, ?, ?, ?)",
            (label, amount, weight, color))
    flash("✅ Приз добавлен.", "success")
    return redirect(url_for("wheel.admin_prizes"))


@bp.route("/admin/prizes/<int:prize_id>/toggle", methods=["POST"])
@admin_required
def admin_prizes_toggle(prize_id):
    p = query_one("SELECT * FROM wheel_prizes WHERE id=?", (prize_id,))
    if not p:
        flash("Приз не найден.", "error")
        return redirect(url_for("wheel.admin_prizes"))
    execute("UPDATE wheel_prizes SET is_active=? WHERE id=?", (0 if p["is_active"] else 1, prize_id))
    flash("✅ Статус приза изменён.", "success")
    return redirect(url_for("wheel.admin_prizes"))


@bp.route("/admin/prizes/<int:prize_id>/delete", methods=["POST"])
@admin_required
def admin_prizes_delete(prize_id):
    execute("DELETE FROM wheel_prizes WHERE id=?", (prize_id,))
    flash("✅ Приз удалён.", "success")
    return redirect(url_for("wheel.admin_prizes"))


@bp.route("/admin/grant", methods=["POST"])
@admin_required
def admin_grant_spin():
    """Ручная выдача бонусного вращения конкретному менеджеру."""
    manager_id = request.form.get("manager_id", type=int)
    manager = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))
    if not manager:
        flash("Менеджер не найден.", "error")
        return redirect(url_for("wheel.admin_prizes"))

    execute("UPDATE managers SET wheel_spins_available = wheel_spins_available + 1 WHERE id=?", (manager_id,))
    notify(manager_id, "🎁 Администратор подарил тебе вращение колеса призов!", url_for("wheel.index"))
    flash(f"✅ Вращение выдано менеджеру {manager['name']}.", "success")
    return redirect(url_for("wheel.admin_prizes"))
