"""Чат-бот команды. Технически — обычный менеджер с ролью 'bot' (никогда
не логинится, is_active=0, исключён из всех обычных списков менеджеров
благодаря фильтрам role='manager', которые уже везде используются).

Три типа поведения:
1. Команды (/баланс, /статистика и т.д.) — личные данные по запросу
2. Автоответы — реагирует на ключевые слова в обычных сообщениях
3. Объявления — сам пишет в чат при значимых событиях (вызывается из хуков
   в других модулях: puzzle.py, wheel.py, referrals.py, contest.py,
   achievements.py, advent_calendar.py)
"""
import os
import secrets

from .db import execute, query_one, query_all

BOT_LOGIN = "system_bot"
_bot_id_cache = {"id": None}


def ensure_bot_account():
    """Создаёт учётку бота один раз при первом старте приложения."""
    existing = query_one("SELECT id FROM managers WHERE login=?", (BOT_LOGIN,))
    if existing:
        _bot_id_cache["id"] = existing["id"]
        return
    from .security import hash_password
    unusable_password = hash_password(secrets.token_hex(32))
    bot_id = execute(
        "INSERT INTO managers (login, password_hash, name, role, is_active) VALUES (?, ?, ?, 'bot', 0)",
        (BOT_LOGIN, unusable_password, "🤖 Бот-помощник"))
    _bot_id_cache["id"] = bot_id


def get_bot_id():
    if _bot_id_cache["id"] is None:
        ensure_bot_account()
    return _bot_id_cache["id"]


def bot_say(text):
    """Публикует сообщение от лица бота в общий чат."""
    execute("INSERT INTO chat_messages (manager_id, message) VALUES (?, ?)", (get_bot_id(), text))


# ==================== 1-10: КОМАНДЫ ====================

def cmd_balance(manager_id):
    m = query_one("SELECT balance FROM managers WHERE id=?", (manager_id,))
    return f"💰 Твой баланс: {m['balance']:.2f}G" if m else "Баланс не найден."


def cmd_stats(manager_id):
    leads_count = query_one(
        "SELECT COUNT(*) c FROM leads WHERE assigned_manager_id=? AND status NOT IN ('declined','unresponsive')",
        (manager_id,))["c"]
    total_sub = query_one("SELECT COUNT(*) c FROM submissions WHERE manager_id=?", (manager_id,))["c"]
    approved_sub = query_one(
        "SELECT COUNT(*) c FROM submissions WHERE manager_id=? AND status='approved'", (manager_id,))["c"]
    conv = round(approved_sub / total_sub * 100, 1) if total_sub else 0
    return f"📊 В работе лидов: {leads_count} · Заявок: {total_sub} · Одобрено: {approved_sub} · Конверсия: {conv}%"


def cmd_referrals(manager_id):
    row = query_one(
        "SELECT COUNT(*) active, COALESCE(SUM(total_override_earned),0) earned "
        "FROM referrals WHERE referrer_id=? AND status='active'", (manager_id,))
    return f"🤝 Активных рефералов: {row['active']} · Заработано с них: {row['earned']:.2f}G"


def cmd_puzzle(manager_id):
    from .puzzle import TOTAL_PIECES, DESIGNS
    m = query_one("SELECT puzzle_current_design FROM managers WHERE id=?", (manager_id,))
    count = query_one("SELECT COUNT(*) c FROM puzzle_pieces WHERE manager_id=?", (manager_id,))["c"]
    design_name = DESIGNS.get(m["puzzle_current_design"], {}).get("name", "?") if m and m["puzzle_current_design"] else "?"
    return f"🧩 {design_name}: собрано {count} из {TOTAL_PIECES}"


def cmd_wheel(manager_id):
    m = query_one("SELECT wheel_spins_available FROM managers WHERE id=?", (manager_id,))
    n = m["wheel_spins_available"] if m else 0
    return f"🎡 Доступно вращений: {n}" if n > 0 else "🎡 Вращений пока нет — одобри ещё заявки!"


def cmd_contest(manager_id):
    from .contest import _current_contest, _leaderboard
    contest = _current_contest()
    if not contest or contest["prizes_paid"]:
        return "🏆 Активного конкурса сейчас нет."
    board = _leaderboard(contest, limit=200)
    place = next((i + 1 for i, r in enumerate(board) if r["manager_id"] == manager_id), None)
    if place:
        row = board[place - 1]
        return f"🏆 Твоё место в «{contest['title']}»: #{place} ({row['approved_count']} заявок)"
    return f"🏆 В «{contest['title']}» у тебя пока нет одобренных заявок — начни зарабатывать место!"


def cmd_achievements(manager_id):
    from .achievements import ACHIEVEMENTS
    count = query_one("SELECT COUNT(*) c FROM manager_achievements WHERE manager_id=?", (manager_id,))["c"]
    return f"🏆 Открыто личных достижений: {count} из {len(ACHIEVEMENTS)}"


def cmd_withdrawal(manager_id):
    w = query_one("SELECT * FROM withdrawals WHERE manager_id=? ORDER BY id DESC LIMIT 1", (manager_id,))
    if not w:
        return "💸 У тебя ещё не было ни одного вывода."
    if w["status"] == "awaiting_listing":
        label = "⏳ ожидает листинга скина"
    elif w["status"] == "proof_submitted":
        label = "📸 скрин продажи на проверке"
    elif w["status"] == "completed" and not w["payout_confirmed"]:
        label = "✅ подтверждён, жду твой скрин выплаты"
    elif w["status"] == "completed" and w["payout_confirmed"] and not w["payout_admin_confirmed"]:
        label = "📥 ждёт финальной проверки администратором"
    elif w["status"] == "rejected":
        label = "❌ отклонён"
    else:
        label = "✅ полностью завершён"
    return f"💸 Последний вывод #{w['id']} на {w['requested_amount']:.2f}G: {label}"


def cmd_top(manager_id):
    rows = query_all("""
        SELECT m.name, COUNT(l.id) c FROM managers m
        LEFT JOIN leads l ON l.assigned_manager_id=m.id AND l.status IN ('participated','returning')
        WHERE m.role='manager' GROUP BY m.id ORDER BY c DESC LIMIT 5
    """)
    lines = [f"{i + 1}. {r['name']} — {r['c']} лидов" for i, r in enumerate(rows)]
    return "🏅 Топ-5 менеджеров:\n" + "\n".join(lines) if lines else "Пока нет данных."


def cmd_help(manager_id):
    return ("🤖 Мои команды:\n"
           "/баланс /статистика /рефералы /пазл /колесо /конкурс /достижения /вывод /топ /помощь")


COMMANDS = {
    "/баланс": cmd_balance,
    "/статистика": cmd_stats,
    "/рефералы": cmd_referrals,
    "/пазл": cmd_puzzle,
    "/колесо": cmd_wheel,
    "/конкурс": cmd_contest,
    "/достижения": cmd_achievements,
    "/вывод": cmd_withdrawal,
    "/топ": cmd_top,
    "/помощь": cmd_help,
}


# ==================== 11-20: АВТООТВЕТЫ ПО КЛЮЧЕВЫМ СЛОВАМ ====================

def _reply_withdraw(mid):
    return ("💸 Чтобы вывести голду: открой «Выводы», укажи сумму от 30G, выстави скин "
           "по расчётной цене из инструкции и следуй шагам на экране.")


def _reply_add_lead(mid):
    return "📋 В разделе «Лиды» вставь ссылку VK (в любом формате) в форму «Добавить лида» — или сначала используй «Проверку лида»."


def _reply_password(mid):
    return "🔑 Пароль восстановить нельзя, только сбросить. Напиши администратору тикет с просьбой сбросить пароль."


def _reply_min_amount(mid):
    return "💰 Минимальная сумма для вывода — 30G."


def _reply_commission(mid):
    from .withdrawals import commission_pct
    return f"💱 Текущая комиссия площадки: {commission_pct()}%."


def _reply_contest_dates(mid):
    from .contest import _current_contest
    c = _current_contest()
    if not c:
        return "🏆 Активного конкурса сейчас нет."
    return f"🏆 «{c['title']}»: с {c['starts_at']} до {c['ends_at']} (UTC)."


def _reply_puzzle_howto(mid):
    return "🧩 За каждую одобренную заявку — случайная часть картины. Собери все 9 — получишь 50-200G, картина останется в коллекции."


def _reply_referral_howto(mid):
    return "🤝 Пригласи менеджера своей ссылкой VK. Когда он одобрит 3 заявки и сделает вывод — тебе 50G разово и 20% с его дохода навсегда."


def _reply_penalty(mid):
    return "⚠️ Штраф 1G списывается при отклонении заявки — например, нечитаемый скриншот или несоответствие раунду."


def _reply_support(mid):
    return "🛠️ Опиши проблему в разделе «Тикеты» — администратор поможет разобраться."


AUTO_REPLIES = [
    (["как вывести", "как выводить"], _reply_withdraw),
    (["как добавить лида"], _reply_add_lead),
    (["забыл пароль", "забыла пароль"], _reply_password),
    (["минимальная сумма"], _reply_min_amount),
    (["комиссия"], _reply_commission),
    (["когда конкурс"], _reply_contest_dates),
    (["что за пазл", "как работает пазл"], _reply_puzzle_howto),
    (["как рефералка", "как работают рефералы", "как реферал"], _reply_referral_howto),
    (["за что штраф", "почему штраф"], _reply_penalty),
    (["не работает", "техподдержка", "тех поддержка"], _reply_support),
]


def handle_autoreply(manager_id, text):
    t = text.lower()
    for triggers, handler in AUTO_REPLIES:
        if any(trig in t for trig in triggers):
            return handler(manager_id)
    return None


def process_incoming_message(manager_id, text):
    """Вызывается из chat.py сразу после сохранения сообщения пользователя."""
    stripped = (text or "").strip()
    if not stripped:
        return
    reply = None
    if stripped.startswith("/"):
        cmd = stripped.split()[0].lower()
        handler = COMMANDS.get(cmd)
        if handler:
            reply = handler(manager_id)
    else:
        reply = handle_autoreply(manager_id, stripped)
    if reply:
        bot_say(reply)


# ==================== 21-30: АВТОМАТИЧЕСКИЕ ОБЪЯВЛЕНИЯ ====================

def announce_new_manager(name):
    bot_say(f"👋 В команде новый менеджер — {name}! Поприветствуйте.")


def announce_contest_start(title, ends_at_human):
    bot_say(f"🏆 Стартовал конкурс «{title}»! Собирай одобренные заявки и попади в топ-9. Финиш: {ends_at_human} (МСК).")


def announce_contest_finish(title, winners):
    lines = [f"{p}. {n} — +{a:.0f}G" for n, p, a in winners[:3]]
    text = f"🏁 Конкурс «{title}» завершён! Топ-3:\n" + "\n".join(lines) if lines else f"🏁 Конкурс «{title}» завершён!"
    bot_say(text)


def announce_puzzle_completed(name, design_name, reward):
    bot_say(f"🧩 {name} собрал(а) картину «{design_name}»! +{reward:.0f}G")


def announce_wheel_big_prize(name, label):
    bot_say(f"🎡 {name} выбил(а) на колесе крупный приз: {label}!")


def announce_referral_activated(referrer_name, referred_name):
    bot_say(f"🤝 Реферальная связь активирована: {referrer_name} ← {referred_name}. Бонус начислен!")


def announce_global_achievement(name, description):
    bot_say(f"🌍 Командное достижение! {name} — {description}")


def announce_calendar_event(event_date, title):
    bot_say(f"🗓️ В календаре новое событие на {event_date}: {title}")


def send_daily_summary():
    pending_sub = query_one("SELECT COUNT(*) c FROM submissions WHERE status='pending'")["c"]
    pending_wd = query_one(
        "SELECT COUNT(*) c FROM withdrawals WHERE status IN ('awaiting_listing','proof_submitted')")["c"]
    bot_say(f"☀️ Доброе утро! На проверке: {pending_sub} заявок, {pending_wd} выводов. Хорошего дня!")


def start_daily_summary_scheduler(app):
    """Утренняя сводка каждый день в 09:00 МСК (06:00 UTC)."""
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return
    if getattr(app, "_chatbot_scheduler_started", False):
        return
    app._chatbot_scheduler_started = True

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(daemon=True)

    def job():
        with app.app_context():
            try:
                send_daily_summary()
            except Exception as e:
                app.logger.error(f"❌ Ошибка утренней сводки бота: {e}")

    scheduler.add_job(job, CronTrigger(hour=6, minute=0))
    scheduler.start()
