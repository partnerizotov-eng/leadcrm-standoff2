"""Уведомления в Telegram — опциональные, best-effort.

Требует TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env (см. config.py).
Если не заданы — send_telegram_message() тихо возвращает False и ничего
не делает, весь остальной функционал CRM продолжает работать как обычно.

⚠️ Это делает реальный HTTP-запрос к api.telegram.org. Я не могу
протестировать фактическую доставку сообщения из своей песочницы (там нет
сети) — код написан по официальному Bot API, но живую проверку нужно
сделать на твоей стороне с реальным токеном.
"""
import requests
from flask import current_app

TELEGRAM_API_TIMEOUT = 10  # секунд — не должно подвешивать запрос пользователя


def is_telegram_configured() -> bool:
    return bool(current_app.config.get("TELEGRAM_BOT_TOKEN") and current_app.config.get("TELEGRAM_CHAT_ID"))


def send_telegram_message(text: str) -> bool:
    """Отправляет сообщение в Telegram. Возвращает True при успехе,
    False при любой проблеме (не настроено, сеть недоступна, невалидный
    токен и т.п.) — никогда не бросает исключение наружу, чтобы сбой
    уведомления не мог сломать основной запрос."""
    token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    chat_id = current_app.config.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=TELEGRAM_API_TIMEOUT,
        )
        return resp.ok
    except requests.RequestException as e:
        try:
            current_app.logger.warning(f"Telegram notify failed: {e}")
        except Exception:
            pass
        return False


def format_risk_digest(report: dict) -> str:
    """Собирает отчёт risk_scoring.compute_risk_report() в текст для Telegram."""
    lines = ["🚨 <b>Риски и дубли — сводка</b>", ""]

    dup_shots = report.get("duplicate_screenshots", [])
    if dup_shots:
        lines.append(f"📷 Переиспользованные скриншоты: {len(dup_shots)} групп(ы)")
    dup_leads = report.get("case_duplicate_leads", [])
    if dup_leads:
        lines.append(f"👤 Лиды-почти-дубли: {len(dup_leads)} пар(ы)")
    outliers = report.get("approval_outliers", [])
    if outliers:
        names = ", ".join(o["name"] for o in outliers[:5])
        lines.append(f"📈 Аномальный % одобрения: {names}")
    bursts = report.get("rapid_bursts", [])
    if bursts:
        names = ", ".join(b["name"] for b in bursts[:5])
        lines.append(f"⚡ Всплески добавления лидов: {names}")

    if len(lines) == 2:
        lines.append("Ничего не найдено — всё чисто ✅")

    return "\n".join(lines)


def send_risk_digest_if_any() -> bool:
    """Собирает риск-отчёт и отправляет в Telegram, только если найдено
    хоть что-то (чтобы не спамить пустыми «всё чисто» сообщениями при
    ежедневном автоматическом запуске). Возвращает True, если отправлено."""
    from .risk_scoring import compute_risk_report
    report = compute_risk_report()
    has_flags = any(report.get(k) for k in
                     ["duplicate_screenshots", "case_duplicate_leads", "approval_outliers", "rapid_bursts"])
    if not has_flags:
        return False
    return send_telegram_message(format_risk_digest(report))


def start_risk_digest_scheduler(app):
    """Раз в сутки прогоняет риск-отчёт и шлёт сводку в Telegram, если
    что-то найдено. Если Telegram не настроен — джоб просто ничего не
    отправляет (is_telegram_configured() проверяется внутри), но
    планировщик всё равно безопасно заводится."""
    import os
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return
    if getattr(app, "_risk_digest_scheduler_started", False):
        return
    app._risk_digest_scheduler_started = True

    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True)

    def job():
        with app.app_context():
            try:
                if is_telegram_configured():
                    sent = send_risk_digest_if_any()
                    if sent:
                        app.logger.info("✅ Ежедневная риск-сводка отправлена в Telegram")
            except Exception as e:
                app.logger.error(f"❌ Ошибка ежедневной риск-сводки: {e}")

    scheduler.add_job(job, "interval", hours=24)
    scheduler.start()
