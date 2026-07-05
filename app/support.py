from flask import Blueprint, render_template, request, redirect, flash, session
from flask_login import login_required, current_user
from .models import SupportTicket, SupportMessage, Manager
from .admin_support import send_support_message, get_ticket_with_messages, close_ticket
from . import db

support_bp = Blueprint('support', __name__, url_prefix='/support')

@support_bp.route('/ticket/<int:ticket_id>')
@login_required
def ticket_detail(ticket_id):
    ticket = SupportTicket.query.get(ticket_id)
    
    if not ticket:
        flash('❌ Ticket не найден', 'error')
        return redirect('/support/manager' if current_user.role != 'admin' else '/support/admin')
    
    # Проверяем доступ (менеджер видит только свои, админ видит все)
    if current_user.role != 'admin' and ticket.manager_id != current_user.id:
        flash('❌ Доступ запрещён', 'error')
        return redirect('/support/manager')
    
    messages = SupportMessage.query.filter_by(ticket_id=ticket_id).order_by(SupportMessage.created_at.asc()).all()
    
    return render_template('support_ticket_detail.html', ticket=ticket, messages=messages)

@support_bp.route('/ticket/<int:ticket_id>/send', methods=['POST'])
@login_required
def ticket_send_message(ticket_id):
    ticket = SupportTicket.query.get(ticket_id)
    
    if not ticket:
        flash('❌ Ticket не найден', 'error')
        return redirect('/support/manager')
    
    # Проверяем доступ
    if current_user.role != 'admin' and ticket.manager_id != current_user.id:
        flash('❌ Доступ запрещён', 'error')
        return redirect('/support/manager')
    
    message = request.form.get('message')
    if not message:
        flash('❌ Сообщение не может быть пустым', 'error')
        return redirect(f'/support/ticket/{ticket_id}')
    
    success, msg = send_support_message(ticket_id, current_user.id, message)
    flash(msg, 'success' if success else 'error')
    return redirect(f'/support/ticket/{ticket_id}')

@support_bp.route('/ticket/<int:ticket_id>/close', methods=['POST'])
@login_required
def ticket_close(ticket_id):
    # Только админ может закрывать
    if current_user.role != 'admin':
        flash('❌ Доступ запрещён', 'error')
        return redirect('/support/manager')
    
    success, msg = close_ticket(ticket_id)
    flash(msg, 'success' if success else 'error')
    return redirect('/support/admin')
