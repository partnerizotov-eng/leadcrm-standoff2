"""Тикеты поддержки — онлайн-чат менеджер <-> админ с вложениями."""
from flask import Blueprint, render_template, request, redirect, flash, session, url_for
from .security import login_required, admin_required
from .db import query_all, query_one
from .admin_support import send_support_message, get_ticket_messages, close_ticket, create_ticket
from .uploads import save_attachment

bp = Blueprint("support_tickets", __name__, url_prefix="/tickets")


@bp.route("/")
@login_required
def index():
    role, manager_id = session["role"], session["manager_id"]

    base_sql = """
        SELECT t.*, m.name as manager_name,
               (SELECT COUNT(*) FROM support_messages WHERE ticket_id = t.id) as message_count
        FROM support_tickets t
        JOIN managers m ON m.id = t.manager_id
    """

    if role == "admin":
        tickets = query_all(base_sql + " ORDER BY t.updated_at DESC")
    else:
        tickets = query_all(base_sql + " WHERE t.manager_id = ? ORDER BY t.updated_at DESC", (manager_id,))

    return render_template("support_tickets.html",
                          tickets=[dict(t) for t in tickets],
                          is_admin=(role == "admin"))


@bp.route("/create", methods=["POST"])
@login_required
def create():
    manager_id = session["manager_id"]
    subject = request.form.get("subject", "").strip()
    message = request.form.get("message", "").strip()

    if not subject or not message:
        flash("Заполните тему и первое сообщение.", "error")
        return redirect(url_for("support_tickets.index"))

    ticket_id = create_ticket(manager_id, subject, message)
    try:
        from .email_notify import notify_admin_email
        notify_admin_email(f"Новый тикет: {subject}", f"{message}\n\n(тикет #{ticket_id})")
    except Exception:
        pass
    flash("✅ Чат с поддержкой открыт.", "success")
    return redirect(url_for("support_tickets.detail", ticket_id=ticket_id))


@bp.route("/<int:ticket_id>")
@login_required
def detail(ticket_id):
    role, manager_id = session["role"], session["manager_id"]

    ticket = query_one("""
        SELECT t.*, m.name as manager_name
        FROM support_tickets t JOIN managers m ON m.id = t.manager_id
        WHERE t.id = ?
    """, (ticket_id,))

    if not ticket:
        flash("Тикет не найден.", "error")
        return redirect(url_for("support_tickets.index"))

    if role != "admin" and ticket["manager_id"] != manager_id:
        flash("Доступ запрещён.", "error")
        return redirect(url_for("support_tickets.index"))

    messages = get_ticket_messages(ticket_id)
    canned = query_all("SELECT id, title, text FROM canned_responses ORDER BY title")

    return render_template("support_ticket_detail.html",
                          ticket=dict(ticket),
                          messages=[dict(m) for m in messages],
                          canned_responses=[dict(c) for c in canned],
                          is_admin=(role == "admin"))


@bp.route("/<int:ticket_id>/send", methods=["POST"])
@login_required
def send(ticket_id):
    role, manager_id = session["role"], session["manager_id"]
    ticket = query_one("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))

    if not ticket:
        flash("Тикет не найден.", "error")
        return redirect(url_for("support_tickets.index"))

    if role != "admin" and ticket["manager_id"] != manager_id:
        flash("Доступ запрещён.", "error")
        return redirect(url_for("support_tickets.index"))

    if ticket["status"] == "closed":
        flash("Тикет закрыт, отправка сообщений невозможна.", "error")
        return redirect(url_for("support_tickets.detail", ticket_id=ticket_id))

    message = request.form.get("message", "").strip()
    forced_kind = request.form.get("attachment_kind") or None
    attachment_path, attachment_type = save_attachment(request.files.get("attachment"), "chat", forced_kind=forced_kind)

    if not message and not attachment_path:
        flash("Напишите сообщение или прикрепите файл.", "error")
        return redirect(url_for("support_tickets.detail", ticket_id=ticket_id))

    send_support_message(ticket_id, manager_id, message, is_admin=(role == "admin"),
                         attachment_path=attachment_path, attachment_type=attachment_type)
    return redirect(url_for("support_tickets.detail", ticket_id=ticket_id))


@bp.route("/<int:ticket_id>/close", methods=["POST"])
@admin_required
def close(ticket_id):
    success, msg = close_ticket(ticket_id)
    flash(msg, "success" if success else "error")
    return redirect(url_for("support_tickets.detail", ticket_id=ticket_id))
