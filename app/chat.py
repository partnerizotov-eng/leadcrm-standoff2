"""Общий чат всей команды. Виден автоматически каждому залогиненному
менеджеру и администратору — отдельного вступления не требуется.
Администратор может временно ограничить менеджеру отправку сообщений
(но не чтение) прямо из интерфейса чата."""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, flash, session, url_for, jsonify

from .db import execute, query_all, query_one
from .security import login_required, admin_required
from .uploads import save_attachment

bp = Blueprint("chat", __name__, url_prefix="/chat")

MESSAGES_PAGE_SIZE = 150

MUTE_PRESETS = {"1h": 1, "1d": 24, "3d": 72, "7d": 168, "30d": 720, "forever": 24 * 365 * 100}
MUTE_LABELS = {
    "1h": "на 1 час", "1d": "на 1 день", "3d": "на 3 дня",
    "7d": "на 7 дней", "30d": "на 30 дней", "forever": "навсегда",
}


def _is_muted(manager):
    if not manager or not manager["chat_muted_until"]:
        return False
    return manager["chat_muted_until"] > datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@bp.route("/")
@login_required
def index():
    manager_id = session["manager_id"]

    rows = query_all("""
        SELECT cm.*, m.name as sender_name, m.role as sender_role
        FROM chat_messages cm JOIN managers m ON m.id = cm.manager_id
        ORDER BY cm.id DESC LIMIT ?
    """, (MESSAGES_PAGE_SIZE,))
    messages = [dict(r) for r in reversed(rows)]

    last_id = messages[-1]["id"] if messages else 0
    execute("""INSERT INTO chat_read_state (manager_id, last_read_id) VALUES (?, ?)
               ON CONFLICT(manager_id) DO UPDATE SET last_read_id=excluded.last_read_id""",
            (manager_id, last_id))

    me = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))
    managers = query_all("SELECT id, name, role, chat_muted_until FROM managers ORDER BY name")

    return render_template("chat.html",
                          messages=messages,
                          is_admin=(session.get("role") == "admin"),
                          my_manager_id=manager_id,
                          i_am_muted=_is_muted(me),
                          my_mute_until=me["chat_muted_until"] if me else None,
                          managers=[dict(m) for m in managers],
                          mute_presets=list(MUTE_PRESETS.keys()),
                          mute_labels=MUTE_LABELS)


@bp.route("/poll")
@login_required
def poll():
    since = request.args.get("since", 0, type=int)
    rows = query_all("""
        SELECT cm.*, m.name as sender_name, m.role as sender_role
        FROM chat_messages cm JOIN managers m ON m.id = cm.manager_id
        WHERE cm.id > ? ORDER BY cm.id ASC LIMIT 100
    """, (since,))
    return jsonify([dict(r) for r in rows])


@bp.route("/send", methods=["POST"])
@login_required
def send():
    manager_id = session["manager_id"]
    me = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))

    if _is_muted(me):
        flash(f"⛔ Вам ограничена отправка сообщений в чат до {me['chat_muted_until']}.", "error")
        return redirect(url_for("chat.index"))

    message = request.form.get("message", "").strip()
    forced_kind = request.form.get("attachment_kind") or None
    attachment_path, attachment_type = save_attachment(request.files.get("attachment"), "chat", forced_kind=forced_kind)

    if not message and not attachment_path:
        flash("Напишите сообщение или прикрепите файл.", "error")
        return redirect(url_for("chat.index"))

    execute("""INSERT INTO chat_messages (manager_id, message, attachment_path, attachment_type)
               VALUES (?, ?, ?, ?)""", (manager_id, message, attachment_path, attachment_type))

    return redirect(url_for("chat.index"))


@bp.route("/mute", methods=["POST"])
@admin_required
def mute():
    target_id = request.form.get("manager_id", type=int)
    preset = request.form.get("preset", "1d")
    hours = MUTE_PRESETS.get(preset, 24)

    target = query_one("SELECT * FROM managers WHERE id=?", (target_id,))
    if not target:
        flash("Менеджер не найден.", "error")
        return redirect(url_for("chat.index"))

    until = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    execute("UPDATE managers SET chat_muted_until=? WHERE id=?", (until, target_id))

    from .notifications import notify
    notify(target_id, f"🔇 Администратор ограничил вашу отправку сообщений в чате {MUTE_LABELS.get(preset, preset)}.",
           url_for("chat.index"))

    flash(f"✅ {target['name']} ограничен в чате {MUTE_LABELS.get(preset, preset)}.", "success")
    return redirect(url_for("chat.index"))


@bp.route("/unmute", methods=["POST"])
@admin_required
def unmute():
    target_id = request.form.get("manager_id", type=int)
    target = query_one("SELECT * FROM managers WHERE id=?", (target_id,))
    if not target:
        flash("Менеджер не найден.", "error")
        return redirect(url_for("chat.index"))

    execute("UPDATE managers SET chat_muted_until=NULL WHERE id=?", (target_id,))

    from .notifications import notify
    notify(target_id, "🔊 Администратор снял ограничение на отправку сообщений в чате.", url_for("chat.index"))

    flash(f"✅ Ограничение для {target['name']} снято.", "success")
    return redirect(url_for("chat.index"))
