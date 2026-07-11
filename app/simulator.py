"""Тренажёр менеджера — публичный раздел (без логина), БЕЗ внешнего ИИ.

Лид и оценка отыгрываются скриптами и правилами прямо в браузере
(см. templates/simulator.html) — ключевые слова, тон, порядок действий.
Бэкенду не нужен ни API-ключ, ни внешние вызовы: раздел работает офлайн.

Итоговая оценка — от 1 до 500, порог прохождения — 450.
"""
from flask import Blueprint, jsonify, render_template, request, session

bp = Blueprint("simulator", __name__, url_prefix="/simulator")

MAX_SCORE = 500
PASS_THRESHOLD = 450

CONTEST_TEXT = """Розыгрыш от паблика. 3 победителя.
Приз: 10 000 Gold в Standoff 2 + редкий нож «Карамбит» на аккаунт победителя.
Условия участия (по шагам):
1) Подписаться на группу ВК.
2) Под актуальным постом с розыгрышем оставить комментарий со своим игровым ID в Standoff 2.
3) Прислать скриншот выполненных условий.
Победители — честный рандом через бота, итоги в прямом эфире.
Участие бесплатное. Приз начисляется на аккаунт — данные для входа (логин/пароль) не нужны."""

# Шаблоны сообщений-подсказок для менеджера — реальные скрипты компании.
# Показываются в тренажёре как «шпаргалка»: вставить/скопировать одним тапом.
HINT_TEMPLATES = [
    {
        "title": "Шаг 1 · Первый контакт",
        "text": ("Привет, вижу тебе нравится Standoff2\n\n"
                  "Я менеджер канала «50G каждый день» по розыгрышам голды в Standoff2; "
                  "каждый день раздаю ребятам по 150G просто за написание ID в игре\n\n"
                  "От тебя ничего не требуется, наш проект полностью легален, расскажу подробнее?"),
    },
    {
        "title": "Шаг 2 · Докажи, что не разводила",
        "text": ("Наш канал по розыгрышам уже насчитывает аудиторию свыше 180 человек, "
                  "которые ежедневно участвуют и побеждают в наших конкурсах\n\n"
                  "Все подтверждения выводов на каждый конкурс у нас есть (скину снизу, это лишь малая часть), "
                  "а вообще со всеми нашими выплатами можешь ознакомиться тут 👉 ВЫПЛАТЫ "
                  "https://vk.me/join/aBNyn6aMZP9LwHbUz0T3al8NMfhYiatduKA=\n\n"
                  "Стало интересно?)"),
    },
    {
        "title": "Шаг 3 · Поторопи к действию",
        "text": ("Переходи скорее в наш канал с розыгрышами и оставляй СВОЙ игровой айди под комментариями "
                  "под текущий розыгрыш; торопись, до конца конкурса 2 часа!\n\n"
                  "Желаю удачи)🍀\n\n"
                  "https://vk.ru/im/channels/-239908136"),
    },
]

# Метаданные персонажей — те же, что были. Сами сценарии реплик и правила
# перехода между шагами живут в simulator.html (JS), чтобы не гонять их
# туда-сюда через сеть: раздел полностью офлайн.
PERSONAS = [
    {"id": "maxon", "codename": "Максон", "handle": "@maxon_sniper", "threat": 1, "color": "#7ED957",
     "tag": "Новичок на позитиве. Легко идёт на контакт."},
    {"id": "denz", "codename": "Дэн", "handle": "@denz.pro", "threat": 4, "color": "#FFC857",
     "tag": "Скептик. Первым делом — «это развод?»."},
    {"id": "kd", "codename": "kd_king", "handle": "@kd_king", "threat": 3, "color": "#2EC5FF",
     "tag": "Молчун. Отвечает односложно."},
    {"id": "vlad", "codename": "Влад", "handle": "@vvvlad_sk", "threat": 3, "color": "#FF8A3D",
     "tag": "Активный, но забывчивый. Обещает и пропадает."},
    {"id": "awp", "codename": "AWP_GOD", "handle": "@AWP_GOD", "threat": 5, "color": "#FF4F6E",
     "tag": "Токсик. Проверяет на прочность."},
]

# Рубрика оценки — тоже только метаданные (имя/вес) для отрисовки экрана
# разбора; сам подсчёт баллов — в JS (scoreTranscript в simulator.html).
RUBRIC = [
    {"key": "opening",      "name": "Заход и первое сообщение", "weight": 15},
    {"key": "clarity",      "name": "Ясность условий",          "weight": 15},
    {"key": "objections",   "name": "Отработка возражений",     "weight": 20},
    {"key": "trust",        "name": "Вызвал доверие",           "weight": 15},
    {"key": "tone",         "name": "Тон и самообладание",      "weight": 10},
    {"key": "conversion",   "name": "Доведение до действия",    "weight": 15},
    {"key": "confirmation", "name": "Подтверждение (скрин)",    "weight": 10},
]


@bp.route("/")
def index():
    return render_template(
        "simulator.html",
        personas=PERSONAS,
        contest=CONTEST_TEXT,
        rubric=RUBRIC,
        hints=HINT_TEMPLATES,
        max_score=MAX_SCORE,
        threshold=PASS_THRESHOLD,
    )


@bp.route("/save-result", methods=["POST"])
def save_result():
    """Раздел /simulator/ остаётся доступен БЕЗ логина (кандидаты без
    аккаунта могут потренироваться). Но если в браузере есть активная
    сессия менеджера — сохраняем его лучший результат в профиль, и при
    первом достижении порога открываем доступ к боевым лидам
    (managers.trainer_passed) — см. security.trainer_required.

    Без сессии — просто отвечаем, что сохранять некуда, это ожидаемо."""
    manager_id = session.get("manager_id")
    if not manager_id:
        return jsonify(saved=False, reason="not_logged_in")

    data = request.get_json(silent=True) or {}
    score = data.get("score")
    passed = bool(data.get("passed"))
    if not isinstance(score, int) or not (1 <= score <= MAX_SCORE):
        return jsonify(saved=False, reason="invalid_score"), 400

    from .db import execute, query_one
    current = query_one("SELECT trainer_passed, trainer_score FROM managers WHERE id=?", (manager_id,))
    if not current:
        return jsonify(saved=False, reason="unknown_manager"), 404

    best_score = max(score, current["trainer_score"] or 0)
    newly_passed = passed and not current["trainer_passed"]
    execute(
        "UPDATE managers SET trainer_score=?, "
        "trainer_passed = CASE WHEN ? THEN 1 ELSE trainer_passed END, "
        "trainer_passed_at = CASE WHEN ? THEN datetime('now') ELSE trainer_passed_at END "
        "WHERE id=?",
        (best_score, 1 if passed else 0, 1 if newly_passed else 0, manager_id))

    try:
        from .achievements import trigger_achievement_check
        trigger_achievement_check(manager_id)
    except Exception:
        pass  # ачивки — бонус, не должны ломать сохранение результата

    return jsonify(saved=True, passed=passed, unlocked=newly_passed, best_score=best_score)
