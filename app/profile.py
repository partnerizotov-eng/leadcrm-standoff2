"""Профиль менеджера — принудительная анкета при первом входе + самостоятельное
редактирование данных, логина и пароля."""
import re
import secrets
import string

from flask import Blueprint, render_template, request, redirect, flash, session, url_for
from .security import login_required, hash_password, verify_password
from .db import query_one, execute, query_all

bp = Blueprint("profile", __name__, url_prefix="/profile")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VK_RE = re.compile(r"^(https?://)?(www\.)?vk\.com/[a-zA-Z0-9_.]{2,50}/?$")
GAME_ID_RE = re.compile(r"^[A-Za-z0-9]{3,20}$")
FULLNAME_RE = re.compile(r"^[А-Яа-яA-Za-zЁё\-]+(\s[А-Яа-яA-Za-zЁё\-]+){1,3}$")


def _validate_profile_fields(full_name, email, vk_url, game_id):
    errors = []
    if not FULLNAME_RE.match(full_name.strip()):
        errors.append("Укажите ФИО полностью — минимум Имя и Фамилия, только буквы.")
    if not EMAIL_RE.match(email.strip()):
        errors.append("Некорректный формат email (пример: name@mail.ru).")
    if not VK_RE.match(vk_url.strip()):
        errors.append("Ссылка на VK должна быть вида vk.com/имя_профиля.")
    if not GAME_ID_RE.match(game_id.strip()):
        errors.append("ID в Standoff 2 — только латинские буквы/цифры, от 3 до 20 символов.")
    return errors


@bp.route("/complete", methods=["GET", "POST"])
@login_required
def complete():
    manager_id = session["manager_id"]
    manager = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))

    if manager["profile_completed"]:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "")
        email = request.form.get("email", "")
        vk_url = request.form.get("vk_url", "")
        game_id = request.form.get("game_id", "")

        consent = request.form.get("consent")

        errors = _validate_profile_fields(full_name, email, vk_url, game_id)
        if not consent:
            errors.append("Необходимо дать согласие на обработку персональных данных.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("profile_complete.html", manager=manager)

        execute("""UPDATE managers SET name=?, email=?, vk_url=?, game_id=?, profile_completed=1, consent_given_at=datetime('now')
                   WHERE id=?""", (full_name.strip(), email.strip(), vk_url.strip(), game_id.strip(), manager_id))

        from .referrals import try_resolve_claims_for_manager
        try_resolve_claims_for_manager(manager_id, vk_url.strip())

        flash("✅ Профиль заполнен, добро пожаловать!", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("profile_complete.html", manager=manager)


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    manager_id = session["manager_id"]
    manager = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "profile":
            full_name = request.form.get("full_name", "")
            email = request.form.get("email", "")
            vk_url = request.form.get("vk_url", "")
            game_id = request.form.get("game_id", "")

            errors = _validate_profile_fields(full_name, email, vk_url, game_id)
            if errors:
                for e in errors:
                    flash(e, "error")
            else:
                execute("UPDATE managers SET name=?, email=?, vk_url=?, game_id=? WHERE id=?",
                        (full_name.strip(), email.strip(), vk_url.strip(), game_id.strip(), manager_id))

                from .referrals import try_resolve_claims_for_manager
                try_resolve_claims_for_manager(manager_id, vk_url.strip())

                flash("✅ Профиль обновлён.", "success")

        elif action == "login":
            new_login = request.form.get("new_login", "").strip()
            current_password = request.form.get("current_password_login", "")

            if not verify_password(current_password, manager["password_hash"]):
                flash("❌ Неверный текущий пароль.", "error")
            elif len(new_login) < 3:
                flash("❌ Логин слишком короткий (минимум 3 символа).", "error")
            else:
                exists = query_one("SELECT id FROM managers WHERE login=? AND id!=?", (new_login, manager_id))
                if exists:
                    flash("❌ Этот логин уже занят.", "error")
                else:
                    execute("UPDATE managers SET login=? WHERE id=?", (new_login, manager_id))
                    session["login"] = new_login
                    flash("✅ Логин изменён.", "success")

        elif action == "password":
            current_password = request.form.get("current_password_pwd", "")
            new_password = request.form.get("new_password", "")
            new_password2 = request.form.get("new_password2", "")

            if not verify_password(current_password, manager["password_hash"]):
                flash("❌ Неверный текущий пароль.", "error")
            elif len(new_password) < 6:
                flash("❌ Новый пароль должен быть не короче 6 символов.", "error")
            elif new_password != new_password2:
                flash("❌ Пароли не совпадают.", "error")
            else:
                execute("UPDATE managers SET password_hash=? WHERE id=?",
                        (hash_password(new_password), manager_id))
                flash("✅ Пароль изменён.", "success")

        manager = query_one("SELECT * FROM managers WHERE id=?", (manager_id,))

    achievements_count = query_one(
        "SELECT COUNT(*) c FROM manager_achievements WHERE manager_id=?", (manager_id,))["c"]
    referrals_active = query_one(
        "SELECT COUNT(*) c FROM referrals WHERE referrer_id=? AND status='active'", (manager_id,))["c"]
    puzzle_owned = query_one(
        "SELECT COUNT(*) c FROM puzzle_pieces WHERE manager_id=?", (manager_id,))["c"]
    puzzles_completed = query_one(
        "SELECT COUNT(*) c FROM puzzle_completions WHERE manager_id=?", (manager_id,))["c"]

    return render_template("profile_settings.html", manager=manager,
                          achievements_count=achievements_count,
                          referrals_active=referrals_active,
                          puzzle_owned=puzzle_owned,
                          puzzles_completed=puzzles_completed)
