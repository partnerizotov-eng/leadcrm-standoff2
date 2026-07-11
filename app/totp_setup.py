"""Двухфакторная аутентификация (2FA) — настройка/включение/выключение.

Специально ограничено ролью admin: через админку идут реальные деньги
(выводы, балансы), это самый чувствительный набор аккаунтов в системе.
Расширить на всех менеджеров легко — заменить admin_required на
login_required здесь; в auth.py уже ничего менять не потребуется (там
проверка totp_enabled не завязана на роль).
"""
import json

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .db import execute, query_one
from .security import admin_required, hash_password, verify_password
from .totp import generate_backup_codes, generate_secret, provisioning_uri, verify_totp

bp = Blueprint("totp_setup", __name__, url_prefix="/profile/2fa")


@bp.route("/")
@admin_required
def index():
    manager = query_one("SELECT totp_enabled FROM managers WHERE id=?", (session["manager_id"],))
    return render_template("totp_setup.html", enabled=bool(manager["totp_enabled"]), setting_up=False)


@bp.route("/setup", methods=["GET", "POST"])
@admin_required
def setup():
    manager = query_one("SELECT * FROM managers WHERE id=?", (session["manager_id"],))
    if manager["totp_enabled"]:
        flash("2FA уже включена.", "error")
        return redirect(url_for("totp_setup.index"))

    if request.method == "POST":
        pending_secret = session.get("totp_pending_secret")
        code = request.form.get("code", "").strip().replace(" ", "")
        if not pending_secret or not verify_totp(pending_secret, code):
            flash("Код неверный — попробуй ещё раз (коды в приложении живут 30 секунд).", "error")
            return redirect(url_for("totp_setup.setup"))

        backup_codes = generate_backup_codes()
        hashed_codes = [hash_password(c) for c in backup_codes]
        execute("UPDATE managers SET totp_secret=?, totp_enabled=1, totp_backup_codes=? WHERE id=?",
                (pending_secret, json.dumps(hashed_codes), manager["id"]))
        session.pop("totp_pending_secret", None)
        session["totp_just_enabled_codes"] = backup_codes  # показать один раз и забыть
        flash("✅ 2FA включена.", "success")
        return redirect(url_for("totp_setup.show_backup_codes"))

    # GET — сгенерировать секрет для показа, но только один раз: если он уже
    # есть в сессии (например, юзер ошибся кодом и его вернуло на эту же
    # страницу), переиспользуем тот же — иначе секрет "уезжает" из-под
    # уже отсканированного QR-кода в приложении при каждой перезагрузке.
    secret = session.get("totp_pending_secret")
    if not secret:
        secret = generate_secret()
        session["totp_pending_secret"] = secret
    uri = provisioning_uri(secret, manager["login"])
    return render_template("totp_setup.html", enabled=False, setting_up=True, secret=secret, uri=uri)


@bp.route("/qr.png")
@admin_required
def qr_code():
    """QR-код для сканирования секрета камерой — по желанию (нужен пакет
    qrcode, `pip install qrcode[pil]`). Если пакета нет — 404, но 2FA
    всё равно полностью работает через ручной ввод секрета/otpauth-ссылки
    в шаблоне, QR — просто удобство, не обязательное условие."""
    from flask import abort, send_file
    secret = session.get("totp_pending_secret")
    if not secret:
        abort(404)
    try:
        import io
        import qrcode
        manager = query_one("SELECT login FROM managers WHERE id=?", (session["manager_id"],))
        uri = provisioning_uri(secret, manager["login"])
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    except ImportError:
        abort(404)


@bp.route("/backup-codes")
@admin_required
def show_backup_codes():
    codes = session.pop("totp_just_enabled_codes", None)
    if not codes:
        return redirect(url_for("totp_setup.index"))
    return render_template("totp_backup_codes.html", codes=codes)


@bp.route("/disable", methods=["POST"])
@admin_required
def disable():
    manager = query_one("SELECT * FROM managers WHERE id=?", (session["manager_id"],))
    password = request.form.get("password", "")
    if not verify_password(password, manager["password_hash"]):
        flash("Неверный пароль — 2FA не отключена.", "error")
        return redirect(url_for("totp_setup.index"))
    execute("UPDATE managers SET totp_secret=NULL, totp_enabled=0, totp_backup_codes=NULL WHERE id=?",
            (manager["id"],))
    flash("2FA отключена.", "success")
    return redirect(url_for("totp_setup.index"))
