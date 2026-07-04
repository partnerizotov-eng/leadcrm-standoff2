"""Система достижений для менеджеров"""
from flask import Blueprint, render_template, session, jsonify
from .db import execute, query_one, query_all
from .security import login_required
from .notifications import notify

bp = Blueprint("achievements", __name__, url_prefix="/achievements")

# Определение всех достижений
ACHIEVEMENTS = {
    "first_lead": {
        "id": "first_lead",
        "name": "🥇 Первый лид",
        "description": "Добавлен первый лид",
        "icon": "🌟",
        "condition": lambda stats: stats.get("total_leads", 0) >= 1
    },
    "lead_hunter": {
        "id": "lead_hunter",
        "name": "🎯 Охотник за лидами",
        "description": "Добавлено 50 лидов",
        "icon": "🏹",
        "condition": lambda stats: stats.get("total_leads", 0) >= 50
    },
    "lead_master": {
        "id": "lead_master",
        "name": "👑 Мастер лидов",
        "description": "Добавлено 100 лидов",
        "icon": "👑",
        "condition": lambda stats: stats.get("total_leads", 0) >= 100
    },
    "first_submission": {
        "id": "first_submission",
        "name": "📸 Первая заявка",
        "description": "Отправлена первая заявка на проверку",
        "icon": "📷",
        "condition": lambda stats: stats.get("total_submissions", 0) >= 1
    },
    "submission_streak": {
        "id": "submission_streak",
        "name": "🔥 Стрелка заявок",
        "description": "10 одобренных заявок подряд",
        "icon": "🔥",
        "condition": lambda stats: stats.get("approved_submissions", 0) >= 10
    },
    "gold_collector": {
        "id": "gold_collector",
        "name": "💰 Собиратель голды",
        "description": "Заработано 100G",
        "icon": "💰",
        "condition": lambda stats: stats.get("total_earned", 0) >= 100
    },
    "gold_millionaire": {
        "id": "gold_millionaire",
        "name": "💎 Голд-миллионер",
        "description": "Заработано 1000G",
        "icon": "💎",
        "condition": lambda stats: stats.get("total_earned", 0) >= 1000
    },
    "conversion_expert": {
        "id": "conversion_expert",
        "name": "🎯 Эксперт конверсии",
        "description": "Конверсия более 50%",
        "icon": "🎯",
        "condition": lambda stats: stats.get("conversion_pct", 0) >= 50
    },
    "conversion_master": {
        "id": "conversion_master",
        "name": "🏆 Мастер конверсии",
        "description": "Конверсия более 70%",
        "icon": "🏆",
        "condition": lambda stats: stats.get("conversion_pct", 0) >= 70
    },
    "seven_day_streak": {
        "id": "seven_day_streak",
        "name": "📅 7 дней активности",
        "description": "Работа 7 дней подряд",
        "icon": "📅",
        "condition": lambda stats: stats.get("streak_days", 0) >= 7
    },
    "thirty_day_streak": {
        "id": "thirty_day_streak",
        "name": "📆 30 дней активности",
        "description": "Работа 30 дней подряд",
        "icon": "📆",
        "condition": lambda stats: stats.get("streak_days", 0) >= 30
    },
    "game_verified": {
        "id": "game_verified",
        "name": "🎮 Верификатор",
        "description": "Привязан первый игровой аккаунт",
        "icon": "🎮",
        "condition": lambda stats: stats.get("game_accounts", 0) >= 1
    },
    "game_master": {
        "id": "game_master",
        "name": "👾 Мастер игры",
        "description": "Привязано 10 игровых аккаунтов",
        "icon": "👾",
        "condition": lambda stats: stats.get("game_accounts", 0) >= 10
    },
    "first_withdrawal": {
        "id": "first_withdrawal",
        "name": "💸 Первый вывод",
        "description": "Выполнен первый вывод в игру",
        "icon": "💸",
        "condition": lambda stats: stats.get("total_withdrawals", 0) >= 1
    },
    "withdrawal_master": {
        "id": "withdrawal_master",
        "name": "💎 Мастер выводов",
        "description": "Выведено 1000G в игру",
        "icon": "💎",
        "condition": lambda stats: stats.get("total_withdrawn", 0) >= 1000
    }
}

def check_achievements(manager_id):
    """Проверка и выдача достижений"""
    # Получение статистики менеджера
    stats = query_one("""
        SELECT 
            COUNT(DISTINCT l.id) as total_leads,
            COUNT(DISTINCT s.id) as total_submissions,
            COUNT(DISTINCT CASE WHEN s.status = 'approved' THEN s.id END) as approved_submissions,
            COALESCE(SUM(CASE WHEN s.status = 'approved' THEN 10 ELSE 0 END), 0) as total_earned,
            COALESCE(ROUND(CAST(COUNT(DISTINCT CASE WHEN l.status IN ('participated', 'returning') THEN l.id END) AS REAL) / 
            NULLIF(COUNT(DISTINCT l.id), 0) * 100, 1), 0) as conversion_pct,
            COUNT(DISTINCT ga.id) as game_accounts,
            COUNT(DISTINCT w.id) as total_withdrawals,
            COALESCE(SUM(w.amount), 0) as total_withdrawn
        FROM managers m
        LEFT JOIN leads l ON l.assigned_manager_id = m.id
        LEFT JOIN submissions s ON s.manager_id = m.id
        LEFT JOIN game_accounts ga ON ga.lead_id = l.id
        LEFT JOIN game_withdrawals w ON w.manager_id = m.id AND w.status = 'completed'
        WHERE m.id = ?
        GROUP BY m.id
    """, (manager_id,))
    
    if not stats:
        return []
    
    # sqlite3.Row неизменяем — работаем со словарём
    stats = dict(stats)
    
    # Подсчет дней подряд
    streak = calculate_streak(manager_id)
    stats["streak_days"] = streak
    
    new_achievements = []
    
    for ach_id, ach in ACHIEVEMENTS.items():
        # Проверка, есть ли уже достижение
        existing = query_one(
            "SELECT id FROM manager_achievements WHERE manager_id = ? AND achievement_id = ?",
            (manager_id, ach_id)
        )
        
        if not existing and ach["condition"](stats):
            # Выдача достижения
            execute("""
                INSERT INTO manager_achievements (manager_id, achievement_id, name, description, icon)
                VALUES (?, ?, ?, ?, ?)
            """, (manager_id, ach_id, ach["name"], ach["description"], ach["icon"]))
            
            new_achievements.append(ach)
            
            # Уведомление
            notify(manager_id, 
                   f"🎉 Новое достижение! {ach['icon']} {ach['name']} - {ach['description']}",
                   "/achievements")
    
    return new_achievements

def calculate_streak(manager_id):
    """Расчет серии дней активности"""
    days = query_all("""
        SELECT DISTINCT DATE(created_at) as day
        FROM activity
        WHERE manager_id = ?
        ORDER BY day DESC
    """, (manager_id,))
    
    if not days:
        return 0
    
    streak = 0
    from datetime import datetime, timedelta
    today = datetime.now().date()
    
    for day in days:
        day_date = datetime.strptime(day["day"], "%Y-%m-%d").date()
        if (today - day_date).days <= streak:
            streak += 1
        else:
            break
    
    return streak

@bp.route("/")
@login_required
def index():
    """Страница достижений"""
    manager_id = session["manager_id"]
    
    # Получение всех достижений менеджера
    achievements = query_all("""
        SELECT * FROM manager_achievements 
        WHERE manager_id = ? 
        ORDER BY unlocked_at DESC
    """, (manager_id,))
    
    # Проверка новых достижений
    new_ach = check_achievements(manager_id)
    
    # Статистика
    total = len(ACHIEVEMENTS)
    unlocked = len(achievements)
    progress = round((unlocked / total * 100), 1) if total > 0 else 0
    
    return render_template("achievements.html",
                          achievements=[dict(a) for a in achievements],
                          all_achievements=ACHIEVEMENTS,
                          total=total,
                          unlocked=unlocked,
                          progress=progress,
                          new_achievements=new_ach)

@bp.route("/check")
@login_required
def check():
    """Проверка новых достижений (AJAX)"""
    manager_id = session["manager_id"]
    new_ach = check_achievements(manager_id)
    return jsonify({"new": [a["name"] for a in new_ach]})

@bp.route("/leaderboard")
@login_required
def leaderboard():
    """Рейтинг по достижениям"""
    managers = query_all("""
        SELECT 
            m.id,
            m.name,
            COUNT(ma.id) as achievements_count,
            GROUP_CONCAT(ma.name, ', ') as achievements_list
        FROM managers m
        LEFT JOIN manager_achievements ma ON ma.manager_id = m.id
        WHERE m.role = 'manager'
        GROUP BY m.id
        ORDER BY achievements_count DESC
        LIMIT 50
    """)
    
    return render_template("achievement_leaderboard.html",
                          managers=[dict(m) for m in managers])