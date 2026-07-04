"""Реферальная система для привлечения новых лидов"""
from flask import Blueprint, render_template, session, request, flash, redirect, url_for
from .db import execute, query_one, query_all
from .security import login_required
from .notifications import notify
from .leads import add_lead

bp = Blueprint("referrals", __name__, url_prefix="/referrals")

REFERRAL_REWARD = 5  # Бонус за приведённого лида

@bp.route("/")
@login_required
def index():
    """Страница реферальной системы"""
    manager_id = session["manager_id"]
    
    # Получение рефералов менеджера
    referrals = query_all("""
        SELECT 
            r.id,
            r.referrer_id,
            r.referred_id,
            r.reward_amount,
            r.status as ref_status,
            r.created_at,
            r.rewarded_at,
            l.name as lead_name,
            l.vk_id,
            l.vk_url,
            l.status as lead_status,
            l.balance,
            l.found_at as lead_created_at
        FROM referrals r
        JOIN leads l ON l.id = r.referred_id
        WHERE r.referrer_id = ?
        ORDER BY r.created_at DESC
    """, (manager_id,))
    
    # Статистика
    stats = query_one("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN r.status = 'rewarded' THEN 1 ELSE 0 END) as rewarded,
            SUM(CASE WHEN r.status = 'pending' THEN 1 ELSE 0 END) as pending,
            COALESCE(SUM(r.reward_amount), 0) as total_rewards
        FROM referrals r
        WHERE r.referrer_id = ?
    """, (manager_id,))
    
    # Реферальная ссылка
    manager = query_one("SELECT login FROM managers WHERE id = ?", (manager_id,))
    ref_link = f"/register?ref={manager['login']}" if manager else ""
    
    return render_template("referrals.html",
                          referrals=[dict(r) for r in referrals],
                          stats=dict(stats) if stats else {"total": 0, "rewarded": 0, "pending": 0, "total_rewards": 0},
                          ref_link=ref_link,
                          reward_amount=REFERRAL_REWARD)

@bp.route("/add", methods=["POST"])
@login_required
def add_referral():
    """Добавление реферала"""
    manager_id = session["manager_id"]
    vk_url = request.form.get("vk_url", "").strip()
    name = request.form.get("name", "").strip()
    source = request.form.get("source", "Реферал")
    
    if not vk_url:
        flash("Укажите ссылку на профиль", "error")
        return redirect(url_for("referrals.index"))
    
    # Добавление лида
    lead_id, created, msg = add_lead(vk_url, source, manager_id, name)
    
    if not lead_id:
        flash(msg or "Не удалось добавить лида", "error")
        return redirect(url_for("referrals.index"))
    
    if not created:
        flash("Этот лид уже существует", "error")
        return redirect(url_for("referrals.index"))
    
    # Создание реферальной записи
    execute("""
        INSERT INTO referrals (referrer_id, referred_id, reward_amount, status)
        VALUES (?, ?, ?, 'pending')
    """, (manager_id, lead_id, REFERRAL_REWARD))
    
    flash(f"✅ Лид добавлен как реферал! После активации вы получите {REFERRAL_REWARD}G", "success")
    return redirect(url_for("referrals.index"))

@bp.route("/reward/<int:referral_id>", methods=["POST"])
@login_required
def reward_referral(referral_id):
    """Начисление бонуса за реферала (только админ)"""
    if session.get("role") != "admin":
        flash("Доступ запрещен", "error")
        return redirect(url_for("referrals.index"))
    
    referral = query_one("SELECT * FROM referrals WHERE id = ?", (referral_id,))
    if not referral:
        flash("Реферал не найден", "error")
        return redirect(url_for("referrals.index"))
    
    if referral["status"] == "rewarded":
        flash("Бонус уже начислен", "error")
        return redirect(url_for("referrals.index"))
    
    # Проверка, что лид активен
    lead = query_one("SELECT * FROM leads WHERE id = ?", (referral["referred_id"],))
    if not lead or lead["status"] in ("declined", "unresponsive"):
        flash("Лид неактивен, бонус не начислен", "error")
        return redirect(url_for("referrals.index"))
    
    # Начисление бонуса
    from . import db
    with db.transaction() as conn:
        # Начисление менеджеру
        conn.execute(
            "UPDATE managers SET balance = balance + ?, total_earned = total_earned + ? WHERE id = ?",
            (REFERRAL_REWARD, REFERRAL_REWARD, referral["referrer_id"])
        )
        
        # Запись в баланс
        conn.execute("""
            INSERT INTO balance_ledger (manager_id, amount, reason, reference_id, note)
            VALUES (?, ?, 'referral_reward', ?, ?)
        """, (referral["referrer_id"], REFERRAL_REWARD, referral_id, f"Бонус за реферала {lead['name']}"))
        
        # Обновление статуса реферала
        conn.execute("""
            UPDATE referrals SET status = 'rewarded', rewarded_at = datetime('now')
            WHERE id = ?
        """, (referral_id,))
    
    # Уведомление
    notify(referral["referrer_id"], 
           f"🎉 Бонус {REFERRAL_REWARD}G за реферала {lead['name']} начислен!",
           "/referrals")
    
    flash(f"✅ Бонус {REFERRAL_REWARD}G начислен", "success")
    return redirect(url_for("referrals.index"))

@bp.route("/register", methods=["GET", "POST"])
def register():
    """Регистрация нового менеджера по реферальной ссылке"""
    ref_code = request.args.get("ref", "")
    
    if request.method == "POST":
        login = request.form.get("login", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()
        ref_code = request.form.get("ref_code", "")
        
        if not all([login, password, name]):
            flash("Заполните все поля", "error")
            return render_template("register.html", ref_code=ref_code)
        
        # Проверка существования
        if query_one("SELECT id FROM managers WHERE login = ?", (login,)):
            flash("Такой логин уже занят", "error")
            return render_template("register.html", ref_code=ref_code)
        
        # Создание менеджера
        from .security import hash_password
        manager_id = execute("""
            INSERT INTO managers (login, password_hash, name, role)
            VALUES (?, ?, ?, 'manager')
        """, (login, hash_password(password), name))
        
        # Если есть реферальный код
        if ref_code:
            referrer = query_one("SELECT id FROM managers WHERE login = ?", (ref_code,))
            if referrer:
                # Создание реферальной записи (за нового менеджера - бонус)
                execute("""
                    INSERT INTO referrals (referrer_id, referred_id, reward_amount, status)
                    VALUES (?, ?, ?, 'pending')
                """, (referrer["id"], manager_id, REFERRAL_REWARD))
                
                notify(referrer["id"], 
                       f"🎉 Новый менеджер {name} зарегистрирован по вашей реферальной ссылке!",
                       "/referrals")
        
        flash("✅ Регистрация успешна! Войдите в систему.", "success")
        return redirect(url_for("auth.login"))
    
    return render_template("register.html", ref_code=ref_code)