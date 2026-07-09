"""Административная панель - все routes"""
from flask import Blueprint, render_template, request, redirect, flash, session, url_for
from .security import admin_required, login_required
from .db import query_all, query_one, execute

from .admin_balance import add_balance, subtract_balance, get_balance_logs
from .admin_players import add_player_balance, get_player_balance_logs
from .admin_leads import delete_lead, get_deleted_leads, restore_lead
from .admin_support import send_support_message, get_ticket_messages, close_ticket, create_ticket
from .admin_payments import (
    upload_payment_proof, upload_top_player_photo, 
    get_payment_proofs, get_top_player_photos,
    delete_payment_proof, delete_top_photo
)
from .admin_top_managers import get_all_managers_stats, get_top_managers_by_metric
from .admin_scripts import (
    get_all_scripts, create_script, delete_script, 
    use_script, init_default_scripts
)
from .vk_integration import (
    get_direct_message_url, get_vk_profile_url,
    parse_vk_id_from_input, is_valid_vk_id
)
from .withdrawals import attach_payment_proof
from .admin_messaging import send_mass_message

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/panel')
@admin_required
def panel():
    """Главная страница админ-панели"""
    
    managers = query_all("SELECT * FROM managers WHERE role = 'manager' AND is_deleted = 0")
    balance_logs = get_balance_logs(50)
    player_balance_logs = get_player_balance_logs(50)
    all_leads = query_all("SELECT l.*, m.name as manager_name FROM leads l LEFT JOIN managers m ON l.assigned_manager_id = m.id")
    deleted_leads = get_deleted_leads(50)
    pending_withdrawals = query_all("SELECT w.*, m.name as manager_name FROM withdrawals w JOIN managers m ON w.manager_id = m.id WHERE w.status = 'awaiting_listing'")
    payment_proofs = get_payment_proofs(50)
    top_player_photos = get_top_player_photos()
    approved_withdrawals = query_all("SELECT w.*, m.name as manager_name FROM withdrawals w JOIN managers m ON w.manager_id = m.id WHERE w.status = 'completed' AND w.payment_proof_id IS NULL")
    paid_withdrawals = query_all("SELECT w.*, m.name as manager_name FROM withdrawals w JOIN managers m ON w.manager_id = m.id WHERE w.status = 'completed' ORDER BY w.updated_at DESC")
    
    all_scripts = get_all_scripts()
    if not all_scripts:
        init_default_scripts(session['manager_id'])
        all_scripts = get_all_scripts()
    
    return render_template('admin_panel.html',
                          managers=[dict(m) for m in managers],
                          balance_logs=[dict(b) for b in balance_logs],
                          player_balance_logs=[dict(p) for p in player_balance_logs],
                          all_leads=[dict(l) for l in all_leads],
                          deleted_leads=[dict(d) for d in deleted_leads],
                          pending_withdrawals=[dict(w) for w in pending_withdrawals],
                          payment_proofs=[dict(p) for p in payment_proofs],
                          top_player_photos=[dict(t) for t in top_player_photos],
                          approved_withdrawals=[dict(a) for a in approved_withdrawals],
                          paid_withdrawals=[dict(p) for p in paid_withdrawals],
                          all_scripts=[dict(s) for s in all_scripts])


# ==================== БАЛАНС МЕНЕДЖЕРОВ ====================

@admin_bp.route('/balance/add', methods=['POST'])
@admin_required
def balance_add():
    manager_id = request.form.get('manager_id', type=int)
    action = request.form.get('action')
    amount = request.form.get('amount', type=float)
    reason = request.form.get('reason')
    admin_id = session['manager_id']
    
    if action == 'add':
        success, msg = add_balance(manager_id, amount, reason, admin_id)
    else:
        success, msg = subtract_balance(manager_id, amount, reason, admin_id)
    
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


# ==================== ГОЛДА ИГРОКАМ ====================

@admin_bp.route('/player/add-balance', methods=['POST'])
@admin_required
def player_add_balance():
    vk_input = request.form.get('vk_input')
    amount = request.form.get('amount', type=float)
    reason = request.form.get('reason')
    admin_id = session['manager_id']
    
    success, msg = add_player_balance(vk_input, amount, reason, admin_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


# ==================== УДАЛЕНИЕ ЛИДОВ ====================

@admin_bp.route('/lead/delete', methods=['POST'])
@admin_required
def lead_delete():
    lead_id = request.form.get('lead_id', type=int)
    admin_comment = request.form.get('admin_comment')
    admin_id = session['manager_id']
    
    success, msg = delete_lead(lead_id, admin_comment, admin_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


@admin_bp.route('/lead/restore', methods=['POST'])
@admin_required
def lead_restore():
    log_id = request.form.get('log_id', type=int)
    
    success, msg = restore_lead(log_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


# ==================== ВЫПЛАТЫ ====================

@admin_bp.route('/payment-proof/upload', methods=['POST'])
@admin_required
def payment_proof_upload():
    file = request.files.get('file')
    withdrawal_id = request.form.get('withdrawal_id', type=int)
    description = request.form.get('description')
    admin_id = session['manager_id']
    
    if withdrawal_id == 0:
        withdrawal_id = None
    
    success, msg = upload_payment_proof(file, withdrawal_id, description, admin_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


@admin_bp.route('/top-player-photo/upload', methods=['POST'])
@admin_required
def top_player_photo_upload():
    file = request.files.get('file')
    description = request.form.get('description')
    admin_id = session['manager_id']
    
    success, msg = upload_top_player_photo(file, description, admin_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


@admin_bp.route('/payment-proof/<int:proof_id>/delete', methods=['POST'])
@admin_required
def payment_proof_delete(proof_id):
    success, msg = delete_payment_proof(proof_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


@admin_bp.route('/top-player-photo/<int:photo_id>/delete', methods=['POST'])
@admin_required
def top_player_photo_delete(photo_id):
    success, msg = delete_top_photo(photo_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


@admin_bp.route('/withdrawal/attach-proof', methods=['POST'])
@admin_required
def withdrawal_attach_proof():
    withdrawal_id = request.form.get('withdrawal_id', type=int)
    file = request.files.get('file')
    description = request.form.get('description', 'Выплата')
    admin_id = session['manager_id']
    
    if not file or file.filename == '':
        flash('❌ Файл не выбран', 'error')
        return redirect(url_for('admin.panel'))
    
    success, msg = upload_payment_proof(file, withdrawal_id, description, admin_id)
    
    if not success:
        flash(msg, 'error')
        return redirect(url_for('admin.panel'))
    
    proof = query_one("SELECT * FROM payment_proofs WHERE withdrawal_id = ? ORDER BY created_at DESC LIMIT 1", (withdrawal_id,))
    
    if proof:
        success, msg = attach_payment_proof(withdrawal_id, proof['id'])
        flash(msg, 'success' if success else 'error')
    
    return redirect(url_for('admin.panel'))


# ==================== ТОП МЕНЕДЖЕРОВ ====================

@admin_bp.route('/top-managers')
@login_required
def top_managers():
    sort = request.args.get('sort', 'leads')

    stats_list = get_all_managers_stats()

    top_by_leads = get_top_managers_by_metric('leads', 5)
    top_by_conversion = get_top_managers_by_metric('conversion', 5)
    top_by_withdrawals = get_top_managers_by_metric('withdrawals', 5)
    top_by_balance = get_top_managers_by_metric('balance', 5)
    top_by_liquidity = get_top_managers_by_metric('liquidity', 5)

    if sort == 'conversion':
        stats_list.sort(key=lambda x: x['conversion_rate'], reverse=True)
    elif sort == 'withdrawals':
        stats_list.sort(key=lambda x: x['stats']['total_withdrawals'], reverse=True)
    elif sort == 'balance':
        stats_list.sort(key=lambda x: x['stats']['balance'], reverse=True)
    elif sort == 'liquidity':
        stats_list.sort(key=lambda x: x['liquidity_score'], reverse=True)
    else:
        stats_list.sort(key=lambda x: x['stats']['total_leads'], reverse=True)

    green_count = len([s for s in stats_list if s['liquidity_score'] >= 75])
    yellow_count = len([s for s in stats_list if 50 <= s['liquidity_score'] < 75])
    orange_count = len([s for s in stats_list if 25 <= s['liquidity_score'] < 50])
    red_count = len([s for s in stats_list if s['liquidity_score'] < 25])

    return render_template('top_managers.html',
                          stats_list=stats_list,
                          is_admin=(session['role'] == 'admin'),
                          top_by_leads=top_by_leads,
                          top_by_conversion=top_by_conversion,
                          top_by_withdrawals=top_by_withdrawals,
                          top_by_balance=top_by_balance,
                          top_by_liquidity=top_by_liquidity,
                          green_count=green_count,
                          yellow_count=yellow_count,
                          orange_count=orange_count,
                          red_count=red_count)


# ==================== СКРИПТЫ ====================

@admin_bp.route('/script/create', methods=['POST'])
@admin_required
def script_create():
    title = request.form.get('title')
    text = request.form.get('text')
    category = request.form.get('category')
    admin_id = session['manager_id']
    
    success, msg = create_script(title, text, category, admin_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


@admin_bp.route('/script/<int:script_id>/delete', methods=['POST'])
@admin_required
def script_delete(script_id):
    success, msg = delete_script(script_id)
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin.panel'))


@admin_bp.route('/script/<int:script_id>/use')
def script_use(script_id):
    vk_id = request.args.get('vk_id')
    lead_id = request.args.get('lead_id', type=int)
    manager_id = session.get('manager_id')
    
    success, msg, text = use_script(script_id, manager_id, vk_id, lead_id)
    
    if success:
        flash(f"✅ Текст скопирован: \"{text[:50]}...\"", 'success')
    else:
        flash(msg, 'error')
    
    return redirect(request.referrer or url_for('leads.index'))


# ==================== VK БЫСТРЫЙ ДОСТУП ====================

@admin_bp.route('/vk-quick-access')
def vk_quick_access():
    vk_input = request.args.get('vk_input')
    action = request.args.get('action', 'profile')
    
    if not vk_input:
        flash('❌ Введи VK ID или ссылку', 'error')
        return redirect(url_for('admin.panel'))
    
    vk_id = parse_vk_id_from_input(vk_input)
    
    if not vk_id or not is_valid_vk_id(vk_id):
        flash('❌ Неверный формат VK ID или ссылки', 'error')
        return redirect(url_for('admin.panel'))
    
    if action == 'chat':
        url = get_direct_message_url(vk_id)
    else:
        url = get_vk_profile_url(vk_id)
    
    if not url:
        flash('❌ Не удалось открыть', 'error')
        return redirect(url_for('admin.panel'))
    
    return redirect(url)


@admin_bp.route('/manager/<int:manager_id>/toggle-active', methods=['POST'])
@admin_required
def manager_toggle_active(manager_id):
    manager = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))
    if not manager:
        flash("Менеджер не найден.", "error")
        return redirect(url_for('admin.panel'))
    new_state = 0 if manager['is_active'] else 1
    execute("UPDATE managers SET is_active=? WHERE id=?", (new_state, manager_id))
    flash(f"✅ Менеджер {manager['name']} теперь {'активен' if new_state else 'заблокирован'}.", "success")
    return redirect(url_for('admin.panel'))


@admin_bp.route('/manager/<int:manager_id>/reset-password', methods=['POST'])
@admin_required
def manager_reset_password(manager_id):
    import secrets as _secrets
    import string as _string
    manager = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))
    if not manager:
        flash("Менеджер не найден.", "error")
        return redirect(url_for('admin.panel'))
    alphabet = _string.ascii_letters + _string.digits
    new_password = ''.join(_secrets.choice(alphabet) for _ in range(10))
    from .security import hash_password
    execute("UPDATE managers SET password_hash=? WHERE id=?", (hash_password(new_password), manager_id))
    flash(f"✅ Новый пароль для {manager['name']}: {new_password} (сохраните — больше не отобразится)", "success")
    return redirect(url_for('admin.panel'))


@admin_bp.route('/messaging')
@admin_required
def messaging():
    managers = query_all("SELECT * FROM managers WHERE role='manager'")
    return render_template('admin_messaging.html', managers=[dict(m) for m in managers])


@admin_bp.route('/messaging/send', methods=['POST'])
@admin_required
def messaging_send():
    message = request.form.get('message', '').strip()
    send_to_all = request.form.get('send_to_all')
    selected_ids = request.form.getlist('manager_ids')

    if not message:
        flash('Сообщение не может быть пустым.', 'error')
        return redirect(url_for('admin.messaging'))

    ids = None if send_to_all else [int(i) for i in selected_ids if i.isdigit()]
    count = send_mass_message(ids, message)
    flash(f'✅ Уведомление отправлено {count} менеджер(ам).', 'success')
    return redirect(url_for('admin.messaging'))
