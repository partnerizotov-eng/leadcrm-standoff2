"""Leads — the core of the tool."""
import re
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from . import db
from .db import execute, log_activity, query_all, query_one
from .security import admin_required, login_required
from .utils import Pagination
from .utils.vk_validator import VKValidator

bp = Blueprint("leads", __name__)

STATUSES = ["new", "contacted", "replied", "joined_channel", "participated", "returning",
           "declined", "unresponsive"]
STATUS_LABELS = {
    "new": "Новый", "contacted": "Написали", "replied": "Ответил",
    "joined_channel": "Вступил в канал", "participated": "Участвовал",
    "returning": "Возвращается", "declined": "Отказался", "unresponsive": "Не отвечает",
}
ROUND_SLOTS = ["12:00", "18:00", "00:00"]


def normalize_vk_id(raw: str) -> str:
    raw = (raw or "").strip().lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = re.sub(r"^(www\.|m\.)?vk\.com/", "", raw)
    raw = raw.lstrip("@").rstrip("/")
    raw = raw.split("?")[0]
    return raw


def next_manager_id():
    row = query_one(
        "SELECT m.id FROM managers m "
        "LEFT JOIN leads l ON l.assigned_manager_id = m.id "
        "AND l.status NOT IN ('declined', 'unresponsive') "
        "WHERE m.role='manager' AND m.is_active=1 "
        "GROUP BY m.id ORDER BY COUNT(l.id) ASC, m.id ASC LIMIT 1")
    return row["id"] if row else None


def add_lead(vk_url, source_group, found_by_manager_id, name="", assign_to_finder=True):
    # Расширенная валидация VK ссылки
    is_valid, message = VKValidator.is_valid_vk_url(vk_url, check_exists=False)
    if not is_valid:
        return None, False, f"❌ {message}"
    
    vk_id = VKValidator.extract_id(vk_url)
    if not vk_id:
        return None, False, "❌ Не удалось распознать VK ID"

    # Проверка на дубликат
    existing = query_one("SELECT id FROM leads WHERE vk_id=?", (vk_id,))
    if existing:
        return existing["id"], False, "⚠️ Лид уже существует"

    manager_id = found_by_manager_id if assign_to_finder else next_manager_id()
    lead_id = execute(
        "INSERT INTO leads (vk_id, vk_url, name, source_group, assigned_manager_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (vk_id, vk_url.strip(), name.strip(), source_group.strip(), manager_id))
    return lead_id, True, "✅ Лид добавлен"


def bulk_import(lines, source_group, assigned_manager_id=None):
    """Массовый импорт с указанием менеджера"""
    added = 0
    duplicates = 0
    skipped = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Валидация перед импортом
        is_valid, _ = VKValidator.is_valid_vk_url(line, check_exists=False)
        if not is_valid:
            skipped += 1
            continue
        
        # Проверяем существование
        vk_id = VKValidator.extract_id(line)
        existing = query_one("SELECT id FROM leads WHERE vk_id=?", (vk_id,))
        if existing:
            duplicates += 1
            continue
        
        # Если менеджер указан - назначаем его, иначе - round-robin
        manager_id = assigned_manager_id if assigned_manager_id else next_manager_id()
        
        execute(
            "INSERT INTO leads (vk_id, vk_url, name, source_group, assigned_manager_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (vk_id, line.strip(), "", source_group.strip(), manager_id))
        added += 1
    
    return added, duplicates, skipped


def vk_chat_url(vk_id: str) -> str:
    return f"https://vk.com/im?sel={vk_id}"


def _can_touch(lead, manager_id, role):
    return role == "admin" or lead["assigned_manager_id"] == manager_id


@bp.route("/leads")
@login_required
def index():
    manager_id = session["manager_id"]
    role = session["role"]
    status_filter = request.args.get("status", "")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    if role == "admin":
        base = "SELECT l.*, m.name manager_name FROM leads l LEFT JOIN managers m ON m.id=l.assigned_manager_id"
        where, params = [], []
    else:
        base = "SELECT l.*, m.name manager_name FROM leads l LEFT JOIN managers m ON m.id=l.assigned_manager_id"
        where, params = ["l.assigned_manager_id=?"], [manager_id]

    if status_filter:
        where.append("l.status=?")
        params.append(status_filter)

    sql = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY l.found_at DESC LIMIT 200"
    all_leads = query_all(sql, tuple(params))
    
    pagination = Pagination(all_leads, page, per_page)
    scripts = query_all("SELECT id, label FROM scripts WHERE is_active=1 ORDER BY label")
    
    return render_template("leads.html", 
                          leads=[dict(r) for r in pagination.current_items],
                          pagination=pagination,
                          scripts=[dict(s) for s in scripts],
                          statuses=STATUSES, 
                          status_labels=STATUS_LABELS, 
                          status_filter=status_filter,
                          is_admin=(role == "admin"))


@bp.route("/leads/add", methods=["POST"])
@login_required
def add():
    manager_id = session["manager_id"]
    vk_url = request.form.get("vk_url", "").strip()
    source_group = request.form.get("source_group", "").strip()
    name = request.form.get("name", "").strip()
    
    if not vk_url:
        flash("❌ Укажите ссылку на профиль ВК.", "error")
        return redirect(url_for("leads.index"))
    
    is_valid, message = VKValidator.is_valid_vk_url(vk_url, check_exists=False)
    if not is_valid:
        flash(f"❌ {message}", "error")
        return redirect(url_for("leads.index"))

    lead_id, created, msg = add_lead(vk_url, source_group, manager_id, name)
    
    if lead_id is None:
        flash(f"{msg}", "error")
    elif created:
        flash(f"{msg}, назначен вам.", "success")
    else:
        owner = query_one(
            "SELECT m.name, l.status FROM leads l LEFT JOIN managers m ON m.id=l.assigned_manager_id "
            "WHERE l.id=?", (lead_id,))
        flash(f"{msg} — ведёт {owner['name'] if owner else 'неизвестно'} "
             f"(статус: {STATUS_LABELS.get(owner['status'], owner['status'])}). Не пишите повторно.", "warning")
    return redirect(url_for("leads.index"))


@bp.route("/leads/bulk-import", methods=["POST"])
@admin_required
def bulk_import_route():
    """Массовый импорт лидов с выбором менеджера"""
    text = request.form.get("profiles", "")
    source_group = request.form.get("source_group", "").strip()
    manager_id = request.form.get("manager_id")
    
    if not text.strip():
        flash("❌ Введите список ссылок для импорта.", "error")
        return redirect(url_for("leads.index"))
    
    lines = text.splitlines()
    
    # Если менеджер не выбран - используем round-robin
    assigned_manager = None
    manager_name = "автоматически (round-robin)"
    
    if manager_id and manager_id != "":
        manager = query_one("SELECT id, name FROM managers WHERE id=? AND role='manager'", (manager_id,))
        if manager:
            assigned_manager = manager["id"]
            manager_name = manager["name"]
    
    added, duplicates, skipped = bulk_import(lines, source_group, assigned_manager)
    
    flash(f"✅ Добавлено: {added}. Уже были: {duplicates}. Пропущено (неверный формат): {skipped}.", "success")
    flash(f"📌 Лиды назначены: {manager_name}", "info")
    log_activity(f"Админ импортировал {added} лидов, назначены: {manager_name}")
    
    return redirect(url_for("leads.index"))


# Остальные маршруты
@bp.route("/leads/<int:lead_id>/contact", methods=["POST"])
@login_required
def mark_contacted(lead_id):
    manager_id, role = session["manager_id"], session["role"]
    lead = query_one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead or not _can_touch(lead, manager_id, role):
        flash("Лид не найден или не ваш.", "error")
        return redirect(url_for("leads.index"))

    script_id = request.form.get("script_id") or None
    execute("INSERT INTO outreach_log (lead_id, manager_id, script_id) VALUES (?, ?, ?)",
            (lead_id, manager_id, script_id))
    if lead["status"] == "new":
        execute("UPDATE leads SET status='contacted', first_contacted_at=datetime('now'), "
                "last_status_change=datetime('now') WHERE id=?", (lead_id,))
    flash("Отмечено: написали.", "success")
    return redirect(url_for("leads.index"))


@bp.route("/leads/<int:lead_id>/status", methods=["POST"])
@login_required
def update_status(lead_id):
    manager_id, role = session["manager_id"], session["role"]
    lead = query_one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead or not _can_touch(lead, manager_id, role):
        flash("Лид не найден или не ваш.", "error")
        return redirect(url_for("leads.index"))

    new_status = request.form.get("status", "")
    if new_status not in STATUSES:
        flash("Некорректный статус.", "error")
        return redirect(url_for("leads.index"))
    execute("UPDATE leads SET status=?, last_status_change=datetime('now') WHERE id=?",
            (new_status, lead_id))
    flash("Статус обновлён.", "success")
    return redirect(url_for("leads.index"))


@bp.route("/leads/<int:lead_id>/participate", methods=["POST"])
@login_required
def log_participation(lead_id):
    manager_id, role = session["manager_id"], session["role"]
    lead = query_one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead or not _can_touch(lead, manager_id, role):
        flash("Лид не найден или не ваш.", "error")
        return redirect(url_for("leads.index"))

    round_slot = request.form.get("round_slot", "")
    if round_slot not in ROUND_SLOTS:
        flash("Некорректный раунд розыгрыша.", "error")
        return redirect(url_for("leads.index"))
    round_date = request.form.get("round_date") or date.today().isoformat()

    already = query_one("SELECT 1 FROM participation_log WHERE lead_id=? AND round_date=? AND round_slot=?",
                        (lead_id, round_date, round_slot))
    if already:
        flash("Уже отмечено для этого раунда.", "error")
        return redirect(url_for("leads.index"))

    execute("INSERT INTO participation_log (lead_id, round_date, round_slot) VALUES (?, ?, ?)",
            (lead_id, round_date, round_slot))
    count = query_one("SELECT COUNT(*) c FROM participation_log WHERE lead_id=?", (lead_id,))["c"]
    new_status = "returning" if count >= 2 else "participated"
    execute("UPDATE leads SET participation_count=?, status=?, last_status_change=datetime('now') WHERE id=?",
            (count, new_status, lead_id))
    flash(f"Участие засчитано (всего: {count}).", "success")
    return redirect(url_for("leads.index"))


@bp.route("/leads/<int:lead_id>/adjust-balance", methods=["POST"])
@admin_required
def adjust_balance(lead_id):
    lead = query_one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead:
        flash("Лид не найден.", "error")
        return redirect(url_for("leads.index"))

    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0
    if amount == 0:
        flash("Укажите сумму (можно отрицательную).", "error")
        return redirect(url_for("leads.index"))
    note = request.form.get("note", "").strip()
    admin_id = session["manager_id"]

    try:
        with db.transaction() as conn:
            cur = conn.execute("UPDATE leads SET balance = balance + ? WHERE id=? AND balance + ? >= 0",
                               (amount, lead_id, amount))
            if cur.rowcount == 0:
                raise ValueError("would_go_negative")
            conn.execute("INSERT INTO balance_ledger (lead_id, amount, reason, actor_manager_id, note) "
                        "VALUES (?, ?, 'admin_adjustment', ?, ?)", (lead_id, amount, admin_id, note))
    except ValueError:
        flash("Итоговый баланс не может стать отрицательным.", "error")
        return redirect(url_for("leads.index"))

    if lead["assigned_manager_id"]:
        from .notifications import notify
        notify(lead["assigned_manager_id"],
              f"Баланс лида {lead['name'] or lead['vk_id']} изменён на {amount:+.2f}G администратором."
              + (f" Причина: {note}" if note else ""),
              url_for("leads.index"))
    log_activity(f"Ручная корректировка баланса лида {lead['name'] or lead['vk_id']}: {amount:+.2f}G."
                + (f" Причина: {note}" if note else ""), admin_id)
    flash("Баланс обновлён.", "success")
    return redirect(url_for("leads.index"))


@bp.route("/leads/<int:lead_id>")
@login_required
def view(lead_id):
    manager_id = session["manager_id"]
    role = session["role"]
    
    if role == "admin":
        lead = query_one("SELECT * FROM leads WHERE id=?", (lead_id,))
    else:
        lead = query_one("SELECT * FROM leads WHERE id=? AND assigned_manager_id=?", (lead_id, manager_id))
    
    if not lead:
        flash("Лид не найден или не ваш.", "error")
        return redirect(url_for("leads.index"))
    
    scripts = query_all("SELECT id, label FROM scripts WHERE is_active=1 ORDER BY label")
    
    return render_template("lead_detail.html", 
                          lead=dict(lead), 
                          statuses=STATUSES, 
                          status_labels=STATUS_LABELS,
                          scripts=[dict(s) for s in scripts])
