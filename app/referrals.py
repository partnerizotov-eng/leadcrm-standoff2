"""Реферальная система для менеджеров.

Менеджер А приглашает менеджера Б своей ссылкой. Когда Б выполняет условия
активации (3 одобренные заявки + 1 полностью завершённый вывод), А получает
разовый бонус 50G, и с этого момента А получает 20% от каждого дохода Б —
бессрочно, автоматически.
"""
from flask import Blueprint, render_template, session, request, flash, redirect, url_for
from . import db
from .db import execute, query_one, query_all
from .security import login_required
from .notifications import notify
import re

bp = Blueprint("referrals", __name__, url_prefix="/referrals")


def _normalize_vk(raw):
    """Та же нормализация, что и для лидов в leads.py — чтобы разные
    форматы ссылки (с https://, www., @) сравнивались корректно."""
    raw = (raw or "").strip().lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = re.sub(r"^(www\.|m\.)?vk\.com/", "", raw)
    raw = raw.lstrip("@").rstrip("/")
    raw = raw.split("?")[0]
    return raw

ACTIVATION_BONUS = 50
OVERRIDE_PCT = 20
REQUIRED_APPROVED_SUBMISSIONS = 3


@bp.route("/")
@login_required
def index():
    manager_id = session["manager_id"]

    referrals = query_all("""
        SELECT r.*, m.name as referred_name, m.login as referred_login
        FROM referrals r
        JOIN managers m ON m.id = r.referred_id
        WHERE r.referrer_id = ?
        ORDER BY r.created_at DESC
    """, (manager_id,))

    stats = query_one("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_count,
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_count,
            COALESCE(SUM(total_override_earned), 0) + COALESCE(SUM(CASE WHEN status='active' THEN ? ELSE 0 END), 0) as total_earned
        FROM referrals WHERE referrer_id = ?
    """, (ACTIVATION_BONUS, manager_id))

    manager = query_one("SELECT login FROM managers WHERE id = ?", (manager_id,))
    ref_link = url_for("referrals.register", ref=manager["login"], _external=True) if manager else ""

    return render_template("referrals.html",
                          referrals=[dict(r) for r in referrals],
                          stats=dict(stats) if stats else {"total": 0, "active_count": 0, "pending_count": 0, "total_earned": 0},
                          ref_link=ref_link,
                          activation_bonus=ACTIVATION_BONUS,
                          override_pct=OVERRIDE_PCT,
                          required_submissions=REQUIRED_APPROVED_SUBMISSIONS)


@bp.route("/register", methods=["GET", "POST"])
def register():
    """Регистрация нового менеджера по реферальной ссылке."""
    ref_code = request.args.get("ref", "") or request.form.get("ref_code", "")

    if request.method == "POST":
        login = request.form.get("login", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()

        if not all([login, password, name]):
            flash("Заполните все поля", "error")
            return render_template("register.html", ref_code=ref_code)

        if query_one("SELECT id FROM managers WHERE login = ?", (login,)):
            flash("Такой логин уже занят", "error")
            return render_template("register.html", ref_code=ref_code)

        from .security import hash_password
        manager_id = execute("""
            INSERT INTO managers (login, password_hash, name, role)
            VALUES (?, ?, ?, 'manager')
        """, (login, hash_password(password), name))

        if ref_code:
            referrer = query_one("SELECT id, name FROM managers WHERE login = ?", (ref_code,))
            if referrer and referrer["id"] != manager_id:
                execute("""
                    INSERT INTO referrals (referrer_id, referred_id, status)
                    VALUES (?, ?, 'pending')
                """, (referrer["id"], manager_id))
                notify(referrer["id"],
                       f"🎉 Новый менеджер {name} зарегистрирован по вашей ссылке! "
                       f"Как только он одобрит {REQUIRED_APPROVED_SUBMISSIONS} заявки и сделает вывод — вы получите {ACTIVATION_BONUS}G.",
                       "/referrals")

        from .chatbot import announce_new_manager
        announce_new_manager(name)

        flash("✅ Регистрация успешна! Войдите в систему.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html", ref_code=ref_code)


# ==================== ВНУТРЕННИЕ ХУКИ (вызываются из submissions.py / withdrawals.py) ====================

def on_submission_approved(manager_id):
    """Вызывать сразу после одобрения заявки менеджера admin-ом."""
    execute("""UPDATE referrals SET submissions_approved = submissions_approved + 1
               WHERE referred_id=? AND status='pending'""", (manager_id,))
    _check_activation(manager_id)


def on_withdrawal_completed(manager_id):
    """Вызывать, когда вывод менеджера полностью завершён
    (payout_admin_confirmed=1 — финальное подтверждение админом)."""
    execute("""UPDATE referrals SET withdrawal_done = 1
               WHERE referred_id=? AND status='pending'""", (manager_id,))
    _check_activation(manager_id)


def _check_activation(manager_id):
    ref = query_one("SELECT * FROM referrals WHERE referred_id=? AND status='pending'", (manager_id,))
    if not ref:
        return
    if ref["submissions_approved"] >= REQUIRED_APPROVED_SUBMISSIONS and ref["withdrawal_done"]:
        with db.transaction() as conn:
            conn.execute("UPDATE managers SET balance = balance + ?, total_earned = total_earned + ? WHERE id=?",
                        (ACTIVATION_BONUS, ACTIVATION_BONUS, ref["referrer_id"]))
            conn.execute("""INSERT INTO manager_ledger (manager_id, amount, reason, reference_id)
                           VALUES (?, ?, 'referral_activation_bonus', ?)""",
                        (ref["referrer_id"], ACTIVATION_BONUS, ref["id"]))
            conn.execute("UPDATE referrals SET status='active', activated_at=datetime('now') WHERE id=?", (ref["id"],))

        referred = query_one("SELECT name FROM managers WHERE id=?", (manager_id,))
        notify(ref["referrer_id"],
               f"🎉 Реферал {referred['name']} выполнил условия! Начислено {ACTIVATION_BONUS}G. "
               f"Теперь вы получаете {OVERRIDE_PCT}% от всех его будущих доходов — бессрочно.",
               "/referrals")

        referrer_row = query_one("SELECT name FROM managers WHERE id=?", (ref["referrer_id"],))
        from .chatbot import announce_referral_activated
        announce_referral_activated(referrer_row["name"] if referrer_row else "Менеджер", referred["name"])


def apply_referral_override(manager_id, earned_amount, source_reason):
    """Вызывать при любом начислении дохода менеджеру (например, одобрение заявки).
    Если менеджер приведён активным рефералом — реферер получает 20% сверху, автоматически."""
    if earned_amount <= 0:
        return
    ref = query_one("SELECT * FROM referrals WHERE referred_id=? AND status='active'", (manager_id,))
    if not ref:
        return

    override = round(earned_amount * OVERRIDE_PCT / 100, 2)
    if override <= 0:
        return

    with db.transaction() as conn:
        conn.execute("UPDATE managers SET balance = balance + ?, total_earned = total_earned + ? WHERE id=?",
                    (override, override, ref["referrer_id"]))
        conn.execute("""INSERT INTO manager_ledger (manager_id, amount, reason, reference_id, note)
                       VALUES (?, ?, 'referral_override', ?, ?)""",
                    (ref["referrer_id"], override, ref["id"], f"20% от дохода реферала: {source_reason}"))
        conn.execute("UPDATE referrals SET total_override_earned = total_override_earned + ? WHERE id=?",
                    (override, ref["id"]))

    notify(ref["referrer_id"], f"💰 +{override:.2f}G — 20% от дохода вашего реферала ({source_reason})", "/referrals")


# ==================== СОПОСТАВЛЕНИЕ ПО ССЫЛКЕ VK ====================

@bp.route("/claim", methods=["POST"])
@login_required
def claim():
    """Менеджер вставляет ссылку VK человека, которого он позвал как
    менеджера. Если такой менеджер уже зарегистрирован и указал тот же
    VK в своём профиле — реферал засчитывается сразу. Если ещё нет —
    заявка сохраняется и сработает автоматически, как только человек
    заполнит анкету с этой же ссылкой VK."""
    referrer_id = session["manager_id"]
    vk_url = request.form.get("vk_url", "").strip()

    if not vk_url:
        flash("Укажите ссылку на VK-профиль.", "error")
        return redirect(url_for("referrals.index"))

    vk_id = _normalize_vk(vk_url)
    if not vk_id:
        flash("Не удалось распознать ссылку VK.", "error")
        return redirect(url_for("referrals.index"))

    matched = None
    for m in query_all("SELECT id, name, vk_url FROM managers WHERE id != ?", (referrer_id,)):
        if m["vk_url"] and _normalize_vk(m["vk_url"]) == vk_id:
            matched = m
            break

    if matched:
        existing = query_one("SELECT id FROM referrals WHERE referred_id=?", (matched["id"],))
        if existing:
            flash(f"⚠️ {matched['name']} уже привязан к другому пригласившему.", "error")
            return redirect(url_for("referrals.index"))

        execute("INSERT INTO referrals (referrer_id, referred_id, status) VALUES (?, ?, 'pending')",
                (referrer_id, matched["id"]))
        flash(f"✅ {matched['name']} привязан как твой реферал!", "success")
        notify(matched["id"],
               "Тебя указали как приглашённого менеджера. Одобри 3 заявки и сделай 1 вывод — и тот, кто тебя пригласил, получит бонус.",
               "/referrals")
    else:
        existing_claim = query_one(
            "SELECT id FROM referral_claims WHERE referrer_id=? AND vk_id=? AND status='pending'",
            (referrer_id, vk_id))
        if not existing_claim:
            execute("INSERT INTO referral_claims (referrer_id, vk_url, vk_id) VALUES (?, ?, ?)",
                    (referrer_id, vk_url, vk_id))
        flash("✅ Заявка сохранена. Как только человек зарегистрируется и укажет тот же VK в профиле — "
             "реферал подтвердится автоматически.", "success")

    return redirect(url_for("referrals.index"))


def try_resolve_claims_for_manager(manager_id, vk_url):
    """Вызывается из profile.py каждый раз, когда менеджер сохраняет
    свою ссылку VK (при заполнении анкеты или в настройках профиля)."""
    vk_id = _normalize_vk(vk_url)
    if not vk_id:
        return

    claim = query_one(
        "SELECT * FROM referral_claims WHERE vk_id=? AND status='pending' ORDER BY id ASC LIMIT 1",
        (vk_id,))
    if not claim or claim["referrer_id"] == manager_id:
        return

    existing = query_one("SELECT id FROM referrals WHERE referred_id=?", (manager_id,))
    if existing:
        execute("UPDATE referral_claims SET status='matched' WHERE id=?", (claim["id"],))
        return

    ref_id = execute("INSERT INTO referrals (referrer_id, referred_id, status) VALUES (?, ?, 'pending')",
                     (claim["referrer_id"], manager_id))
    execute("UPDATE referral_claims SET status='matched', matched_referral_id=? WHERE id=?",
            (ref_id, claim["id"]))

    referred = query_one("SELECT name FROM managers WHERE id=?", (manager_id,))
    notify(claim["referrer_id"],
           f"🎉 {referred['name']} подтверждён как твой реферал по совпадению VK!",
           "/referrals")
