"""Email-уведомления — опциональные, best-effort, на стандартной
библиотеке (smtplib), тот же принцип, что и telegram_notify.py.

Требует SMTP_HOST/SMTP_USER/SMTP_PASSWORD/SMTP_FROM/ADMIN_EMAIL в .env.
Без них send_email() тихо возвращает False, остальной функционал не
затронут. Реальную доставку я не могу проверить из своей песочницы (там
нет сети) — код написан по стандартному SMTP, но живая проверка — на
твоей стороне с реальными данными почтового сервера.
"""
import smtplib
from email.mime.text import MIMEText

from flask import current_app


def is_email_configured() -> bool:
    c = current_app.config
    return bool(c.get("SMTP_HOST") and c.get("SMTP_USER") and c.get("SMTP_PASSWORD") and c.get("SMTP_FROM"))


def send_email(to_addr: str, subject: str, body: str) -> bool:
    """Отправляет email. Возвращает True при успехе, False при любой
    проблеме (не настроено, сеть недоступна, неверные данные) — никогда
    не бросает исключение наружу."""
    c = current_app.config
    if not is_email_configured() or not to_addr:
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = c["SMTP_FROM"]
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(c["SMTP_HOST"], c["SMTP_PORT"], timeout=10) as server:
            server.starttls()
            server.login(c["SMTP_USER"], c["SMTP_PASSWORD"])
            server.sendmail(c["SMTP_FROM"], [to_addr], msg.as_string())
        return True
    except (smtplib.SMTPException, OSError) as e:
        try:
            current_app.logger.warning(f"Email notify failed: {e}")
        except Exception:
            pass
        return False


def notify_admin_email(subject: str, body: str) -> bool:
    """Уведомление на ADMIN_EMAIL — для крупных выводов, новых тикетов и т.п."""
    addr = current_app.config.get("ADMIN_EMAIL")
    if not addr:
        return False
    return send_email(addr, subject, body)
