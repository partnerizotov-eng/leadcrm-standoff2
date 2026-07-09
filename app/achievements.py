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
    # ⚠️ total_earned теперь берётся напрямую из managers.total_earned — этот столбец
    # уже корректно учитывает заявки, колесо призов, рефералов и конкурсы (обновляется
    # во всех этих местах). Раньше здесь было жёстко "10G за заявку", что игнорировало
    # все остальные источники дохода.
    # ⚠️ total_withdrawals/total_withdrawn теперь считаются по РЕАЛЬНОЙ таблице withdrawals
    # (вывод голды менеджером в деньги через продажу скина), а не по game_withdrawals
    # (это отдельная механика — вывод голды ИГРОКА в саму игру, не относится к менеджеру).
    stats = query_one("""
        SELECT 
            m.total_earned as total_earned,
            COUNT(DISTINCT l.id) as total_leads,
            COUNT(DISTINCT s.id) as total_submissions,
            COUNT(DISTINCT CASE WHEN s.status = 'approved' THEN s.id END) as approved_submissions,
            COALESCE(ROUND(CAST(COUNT(DISTINCT CASE WHEN l.status IN ('participated', 'returning') THEN l.id END) AS REAL) / 
            NULLIF(COUNT(DISTINCT l.id), 0) * 100, 1), 0) as conversion_pct,
            COUNT(DISTINCT ga.id) as game_accounts,
            COUNT(DISTINCT CASE WHEN w.payout_admin_confirmed=1 THEN w.id END) as total_withdrawals,
            COALESCE(SUM(CASE WHEN w.payout_admin_confirmed=1 THEN w.requested_amount ELSE 0 END), 0) as total_withdrawn
        FROM managers m
        LEFT JOIN leads l ON l.assigned_manager_id = m.id
        LEFT JOIN submissions s ON s.manager_id = m.id
        LEFT JOIN game_accounts ga ON ga.lead_id = l.id
        LEFT JOIN withdrawals w ON w.manager_id = m.id
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

def trigger_achievement_check(manager_id):
    """Публичная точка входа для мгновенной проверки достижений сразу после
    события (одобрение заявки, завершённый вывод) — вместо ожидания захода
    менеджера на страницу «Достижения»."""
    check_achievements(manager_id)
    check_global_achievements()


# ==================== ГЛОБАЛЬНЫЕ (КОМАНДНЫЕ) ДОСТИЖЕНИЯ ====================
# В отличие от личных, эти разблокируются один раз на весь проект и видны
# всем менеджерам сразу — как командный милстоун, а не личный прогресс.

GLOBAL_ACHIEVEMENTS = {
    "team_100_approved": {
        "id": "team_100_approved", "name": "🎯 Сотня одобрений",
        "description": "Команда суммарно получила 100 одобренных заявок", "icon": "🎯",
        "condition": lambda s: s.get("total_approved", 0) >= 100,
    },
    "team_500_approved": {
        "id": "team_500_approved", "name": "🚀 Пятьсот одобрений",
        "description": "Команда суммарно получила 500 одобренных заявок", "icon": "🚀",
        "condition": lambda s: s.get("total_approved", 0) >= 500,
    },
    "team_10_managers": {
        "id": "team_10_managers", "name": "👥 Полная команда",
        "description": "В проекте работает 10 и более активных менеджеров", "icon": "👥",
        "condition": lambda s: s.get("active_managers", 0) >= 10,
    },
    "team_10_withdrawals": {
        "id": "team_10_withdrawals", "name": "💰 Первые 10 выводов",
        "description": "Команда завершила 10 подтверждённых выводов голды", "icon": "💰",
        "condition": lambda s: s.get("total_withdrawals", 0) >= 10,
    },
    "team_50000_earned": {
        "id": "team_50000_earned", "name": "💎 50 000G заработано командой",
        "description": "Суммарный заработок всей команды достиг 50 000G", "icon": "💎",
        "condition": lambda s: s.get("total_earned_team", 0) >= 50000,
    },
    "team_5_referrals": {
        "id": "team_5_referrals", "name": "🤝 Реферальная сеть",
        "description": "5 активных реферальных связей внутри команды", "icon": "🤝",
        "condition": lambda s: s.get("active_referrals", 0) >= 5,
    },
}


def check_global_achievements():
    row = query_one("""
        SELECT
            COALESCE(SUM(m.total_earned), 0) as total_earned_team,
            COUNT(DISTINCT CASE WHEN m.role='manager' AND m.is_active=1 THEN m.id END) as active_managers
        FROM managers m
    """)
    team_stats = dict(row) if row else {}

    approved_row = query_one("SELECT COUNT(*) c FROM submissions WHERE status='approved'")
    team_stats["total_approved"] = approved_row["c"] if approved_row else 0

    wd_row = query_one("SELECT COUNT(*) c FROM withdrawals WHERE payout_admin_confirmed=1")
    team_stats["total_withdrawals"] = wd_row["c"] if wd_row else 0

    ref_row = query_one("SELECT COUNT(*) c FROM referrals WHERE status='active'")
    team_stats["active_referrals"] = ref_row["c"] if ref_row else 0

    new_global = []
    for ach_id, ach in GLOBAL_ACHIEVEMENTS.items():
        existing = query_one("SELECT id FROM global_achievements WHERE achievement_id=?", (ach_id,))
        if not existing and ach["condition"](team_stats):
            execute("""INSERT INTO global_achievements (achievement_id, name, description, icon)
                       VALUES (?, ?, ?, ?)""", (ach_id, ach["name"], ach["description"], ach["icon"]))
            new_global.append(ach)

            managers = query_all("SELECT id FROM managers")
            for m in managers:
                notify(m["id"],
                       f"🌍 Командное достижение разблокировано! {ach['icon']} {ach['name']} — {ach['description']}",
                       "/achievements")

            from .chatbot import announce_global_achievement
            announce_global_achievement(f"{ach['icon']} {ach['name']}", ach['description'])

    return new_global


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
    new_global = check_global_achievements()

    global_achievements = query_all("SELECT * FROM global_achievements ORDER BY unlocked_at DESC")

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
                          new_achievements=new_ach,
                          global_achievements=[dict(g) for g in global_achievements],
                          all_global_achievements=GLOBAL_ACHIEVEMENTS,
                          new_global=new_global)

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