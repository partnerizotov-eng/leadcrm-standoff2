"""Push-уведомления в браузере (Web Push API) — самый инфраструктурно
тяжёлый пункт из всего списка: нужны VAPID-ключи, подписка через
Service Worker в браузере и пакет `pip install pywebpush`. Без этого
всё продолжает работать как обычно — просто без push (in-app и
notifications.notify() никуда не делись).

⚠️ Честно: я не могу проверить реальную доставку push-уведомления из
своей песочницы — там нет ни браузера, ни реального Service Worker,
ни сети. Код написан по стандартному Web Push протоколу (тот же принцип,
что Telegram/email/S3 в этом раунде), но живую проверку — с реальными
VAPID-ключами и подпиской из настоящего браузера — нужно делать у себя.
"""
import json

from flask import Blueprint, current_app, jsonify, request, session

from .db import execute, query_all
from .security import login_required

bp = Blueprint("push", __name__, url_prefix="/push")


def is_push_configured() -> bool:
    c = current_app.config
    return bool(c.get("VAPID_PRIVATE_KEY") and c.get("VAPID_PUBLIC_KEY"))


@bp.route("/vapid-public-key")
@login_required
def vapid_public_key():
    """Отдаёт публичный ключ фронту — нужен для subscribe() в Service Worker."""
    return jsonify(key=current_app.config.get("VAPID_PUBLIC_KEY", ""))


@bp.route("/subscribe", methods=["POST"])
@login_required
def subscribe():
    """Сохраняет подписку браузера на push (вызывается из JS после
    успешного pushManager.subscribe())."""
    sub = request.get_json(silent=True) or {}
    endpoint = sub.get("endpoint")
    if not endpoint:
        return jsonify(ok=False, error="no endpoint"), 400
    execute(
        "INSERT INTO push_subscriptions (manager_id, endpoint, subscription_json) VALUES (?, ?, ?) "
        "ON CONFLICT(endpoint) DO UPDATE SET subscription_json=excluded.subscription_json",
        (session["manager_id"], endpoint, json.dumps(sub)))
    return jsonify(ok=True)


@bp.route("/unsubscribe", methods=["POST"])
@login_required
def unsubscribe():
    endpoint = (request.get_json(silent=True) or {}).get("endpoint")
    if endpoint:
        execute("DELETE FROM push_subscriptions WHERE endpoint=? AND manager_id=?",
                (endpoint, session["manager_id"]))
    return jsonify(ok=True)


def send_push_to_manager(manager_id: int, title: str, body: str, url: str = "/") -> int:
    """Отправляет push всем подпискам менеджера. Возвращает число успешных
    отправок. Тихо возвращает 0, если pywebpush не установлен или VAPID
    не настроен — никогда не бросает исключение наружу."""
    if not is_push_configured():
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return 0

    rows = query_all("SELECT endpoint, subscription_json FROM push_subscriptions WHERE manager_id=?",
                      (manager_id,))
    sent = 0
    payload = json.dumps({"title": title, "body": body, "url": url})
    for row in rows:
        try:
            webpush(
                subscription_info=json.loads(row["subscription_json"]),
                data=payload,
                vapid_private_key=current_app.config["VAPID_PRIVATE_KEY"],
                vapid_claims={"sub": f"mailto:{current_app.config['VAPID_CLAIMS_EMAIL']}"},
            )
            sent += 1
        except WebPushException:
            # Подписка протухла (браузер отписался/закрылся навсегда) —
            # удаляем её, чтобы не пытаться снова и снова.
            execute("DELETE FROM push_subscriptions WHERE endpoint=?", (row["endpoint"],))
        except Exception:
            pass
    return sent
