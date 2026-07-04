from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .db import execute, query_all, query_one
from .security import login_required

bp = Blueprint("scripts", __name__)


@bp.route("/scripts")
@login_required
def index():
    scripts = query_all("""
        SELECT s.*, 
               (SELECT COUNT(*) FROM outreach_log WHERE script_id=s.id) as times_used,
               (SELECT COUNT(*) FROM outreach_log WHERE script_id=s.id AND response='replied') as times_replied
        FROM scripts s 
        ORDER BY s.is_active DESC, s.id DESC
    """)
    
    result = []
    for s in scripts:
        d = dict(s)
        d["reply_rate"] = round(d["times_replied"] / d["times_used"] * 100) if d["times_used"] and d["times_used"] > 0 else None
        result.append(d)
    
    return render_template("scripts.html", scripts=result)


@bp.route("/scripts/create", methods=["POST"])
@login_required
def create():
    label = request.form.get("label", "").strip()
    body = request.form.get("body", "").strip()
    category = request.form.get("category", "Другое").strip()
    
    if not (label and body):
        flash("Заполните название и текст скрипта.", "error")
        return redirect(url_for("scripts.index"))
    
    execute("INSERT INTO scripts (label, body, category, created_by) VALUES (?, ?, ?, ?)",
            (label, body, category, session["manager_id"]))
    
    flash("✅ Скрипт добавлен.", "success")
    return redirect(url_for("scripts.index"))


@bp.route("/scripts/<int:script_id>/toggle", methods=["POST"])
@login_required
def toggle(script_id):
    if not query_one("SELECT 1 FROM scripts WHERE id=?", (script_id,)):
        flash("Скрипт не найден.", "error")
        return redirect(url_for("scripts.index"))
    
    execute("UPDATE scripts SET is_active = 1 - is_active WHERE id=?", (script_id,))
    flash("Статус скрипта обновлён.", "success")
    return redirect(url_for("scripts.index"))


@bp.route("/scripts/<int:script_id>/preview")
@login_required
def preview(script_id):
    """Предпросмотр скрипта с подстановкой имени"""
    script = query_one("SELECT * FROM scripts WHERE id=?", (script_id,))
    if not script:
        return {"error": "Скрипт не найден"}, 404
    
    # Получаем имя менеджера
    manager = query_one("SELECT name FROM managers WHERE id=?", (session["manager_id"],))
    manager_name = manager["name"] if manager else "Менеджер"
    
    # Получаем имя лида для примера
    lead = query_one("SELECT name FROM leads LIMIT 1")
    lead_name = lead["name"] if lead else "Игрок"
    
    # Подставляем имя менеджера в скрипт
    body = script["body"]
    body = body.replace("{manager}", manager_name)
    body = body.replace("{name}", lead_name)
    
    return {"body": body, "label": script["label"]}