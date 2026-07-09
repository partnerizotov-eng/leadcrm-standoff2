"""Мини-игра «Пазл». За каждую одобренную заявку менеджер получает одну
случайную из 9 частей ТЕКУЩЕЙ картины (части могут повторяться — это часть
механики коллекционирования). Когда собраны все 9 уникальных частей —
картина засчитывается в личную коллекцию менеджера навсегда, начисляется
случайный бонус 50-200G, и для нового цикла случайно выбирается одна
из 6 картин (может повториться — как и с самими частями)."""
import random

from flask import Blueprint, render_template, session, jsonify

from . import db
from .db import execute, query_one, query_all
from .security import login_required
from .notifications import notify

bp = Blueprint("puzzle", __name__, url_prefix="/puzzle")

TOTAL_PIECES = 9
REWARD_MIN = 50
REWARD_MAX = 200

import base64

# Каждая картина — это готовое SVG-изображение (не файл на диске, а текст
# прямо в коде, поэтому не может слететь при пересборке контейнера).
# Внутри: цветной фон-градиент + крупный узнаваемый силуэт по центру —
# так при раскрытии видно не абстрактное цветовое пятно, а реальную часть
# понятной картинки (пламя, кристалл, самоцвет, меч, дерево, закат).

_SVG_TEMPLATES = {
    "fire": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'>
        <defs><radialGradient id='g' cx='50%' cy='42%' r='75%'>
        <stop offset='0%' stop-color='#FFE9A8'/><stop offset='55%' stop-color='#E9B949'/>
        <stop offset='100%' stop-color='#8B3A1F'/></radialGradient></defs>
        <rect width='300' height='300' fill='url(#g)'/>
        <path d='M150,55 C112,105 90,150 90,192 C90,235 117,262 150,262 C183,262 210,235 210,192 C210,150 188,105 150,55 Z' fill='#E56B6B' opacity='0.92'/>
        <path d='M150,112 C130,142 118,170 118,196 C118,218 132,235 150,235 C168,235 182,218 182,196 C182,170 170,142 150,112 Z' fill='#FFD700'/>
        </svg>""",
    "ice": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'>
        <defs><radialGradient id='g' cx='50%' cy='42%' r='75%'>
        <stop offset='0%' stop-color='#EAF7FF'/><stop offset='55%' stop-color='#6C8CFF'/>
        <stop offset='100%' stop-color='#1B2A5E'/></radialGradient></defs>
        <rect width='300' height='300' fill='url(#g)'/>
        <polygon points='150,45 232,195 68,195' fill='#E8F4FF' opacity='0.9'/>
        <polygon points='150,255 68,105 232,105' fill='#B8E8FF' opacity='0.9'/>
        <circle cx='150' cy='150' r='18' fill='#FFFFFF'/>
        </svg>""",
    "gold_dragon": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'>
        <defs><radialGradient id='g' cx='50%' cy='42%' r='75%'>
        <stop offset='0%' stop-color='#FFF3C4'/><stop offset='55%' stop-color='#FFD700'/>
        <stop offset='100%' stop-color='#8B5A00'/></radialGradient></defs>
        <rect width='300' height='300' fill='url(#g)'/>
        <polygon points='150,42 218,122 190,262 110,262 82,122' fill='#FFEA70' opacity='0.95'/>
        <polygon points='150,42 150,262 110,262 82,122' fill='#FFFFFF' opacity='0.25'/>
        <line x1='150' y1='150' x2='150' y2='42' stroke='#8B5A00' stroke-width='3'/>
        <line x1='150' y1='150' x2='218' y2='122' stroke='#8B5A00' stroke-width='3'/>
        <line x1='150' y1='150' x2='190' y2='262' stroke='#8B5A00' stroke-width='3'/>
        <line x1='150' y1='150' x2='110' y2='262' stroke='#8B5A00' stroke-width='3'/>
        <line x1='150' y1='150' x2='82' y2='122' stroke='#8B5A00' stroke-width='3'/>
        </svg>""",
    "shadow": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'>
        <defs><radialGradient id='g' cx='50%' cy='42%' r='75%'>
        <stop offset='0%' stop-color='#B58CFF'/><stop offset='55%' stop-color='#4B2E83'/>
        <stop offset='100%' stop-color='#150E2B'/></radialGradient></defs>
        <rect width='300' height='300' fill='url(#g)'/>
        <polygon points='150,40 168,182 150,204 132,182' fill='#E8E4FF' opacity='0.95'/>
        <rect x='108' y='182' width='84' height='16' rx='4' fill='#E8E4FF' opacity='0.9'/>
        <rect x='138' y='198' width='24' height='52' rx='6' fill='#B58CFF'/>
        <circle cx='150' cy='256' r='16' fill='#E8E4FF'/>
        </svg>""",
    "emerald": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'>
        <defs><radialGradient id='g' cx='50%' cy='42%' r='75%'>
        <stop offset='0%' stop-color='#B6FFDC'/><stop offset='55%' stop-color='#3ECF8E'/>
        <stop offset='100%' stop-color='#0F4A32'/></radialGradient></defs>
        <rect width='300' height='300' fill='url(#g)'/>
        <polygon points='150,48 182,120 118,120' fill='#A8FFD1' opacity='0.95'/>
        <polygon points='150,82 202,172 98,172' fill='#6FE0A8' opacity='0.95'/>
        <polygon points='150,122 224,224 76,224' fill='#3ECF8E' opacity='0.95'/>
        <rect x='134' y='224' width='32' height='46' fill='#8B5A2B'/>
        </svg>""",
    "crimson": """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'>
        <defs><radialGradient id='g' cx='50%' cy='38%' r='75%'>
        <stop offset='0%' stop-color='#FFD199'/><stop offset='55%' stop-color='#E56B6B'/>
        <stop offset='100%' stop-color='#5A1224'/></radialGradient></defs>
        <rect width='300' height='300' fill='url(#g)'/>
        <circle cx='150' cy='118' r='58' fill='#FFEA70' opacity='0.95'/>
        <polygon points='24,262 108,140 168,205 222,110 276,262' fill='#8B1E3F' opacity='0.92'/>
        </svg>""",
}


def _svg_to_data_uri(svg_text):
    encoded = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
    return f"url('data:image/svg+xml;base64,{encoded}')"


DESIGNS = {
    "fire": {"name": "🔥 Огненный феникс", "image": _svg_to_data_uri(_SVG_TEMPLATES["fire"])},
    "ice": {"name": "❄️ Ледяной страж", "image": _svg_to_data_uri(_SVG_TEMPLATES["ice"])},
    "gold_dragon": {"name": "🐉 Золотой самоцвет", "image": _svg_to_data_uri(_SVG_TEMPLATES["gold_dragon"])},
    "shadow": {"name": "🌑 Клинок тени", "image": _svg_to_data_uri(_SVG_TEMPLATES["shadow"])},
    "emerald": {"name": "💚 Изумрудный лес", "image": _svg_to_data_uri(_SVG_TEMPLATES["emerald"])},
    "crimson": {"name": "🩸 Багровый закат", "image": _svg_to_data_uri(_SVG_TEMPLATES["crimson"])},
}
DESIGN_IDS = list(DESIGNS.keys())


def _ensure_current_design(manager_id, manager_row=None):
    """Гарантирует, что у менеджера выбрана текущая картина цикла — если
    ещё нет (новый менеджер или первый заход), выбирает случайную."""
    m = manager_row or query_one("SELECT puzzle_current_design FROM managers WHERE id=?", (manager_id,))
    if m and m["puzzle_current_design"] and m["puzzle_current_design"] in DESIGNS:
        return m["puzzle_current_design"]
    design_id = random.choice(DESIGN_IDS)
    execute("UPDATE managers SET puzzle_current_design=? WHERE id=?", (design_id, manager_id))
    return design_id


def grant_piece_on_approval(manager_id):
    """Вызывать сразу после одобрения заявки менеджера."""
    _ensure_current_design(manager_id)
    piece_index = random.randint(0, TOTAL_PIECES - 1)

    existing = query_one(
        "SELECT id FROM puzzle_pieces WHERE manager_id=? AND piece_index=?", (manager_id, piece_index))

    if not existing:
        execute("INSERT INTO puzzle_pieces (manager_id, piece_index) VALUES (?, ?)", (manager_id, piece_index))
        notify(manager_id, f"🧩 Новая часть картины проявлена! ({piece_index + 1}/{TOTAL_PIECES})", "/puzzle")
    else:
        notify(manager_id, "🧩 Часть повторилась — но не расстраивайся, собери остальные!", "/puzzle")

    _check_completion(manager_id)


def _check_completion(manager_id):
    count = query_one("SELECT COUNT(*) c FROM puzzle_pieces WHERE manager_id=?", (manager_id,))["c"]
    if count < TOTAL_PIECES:
        return

    manager = query_one("SELECT puzzle_current_design FROM managers WHERE id=?", (manager_id,))
    design_id = _ensure_current_design(manager_id, manager)
    reward = random.randint(REWARD_MIN, REWARD_MAX)
    next_design = random.choice(DESIGN_IDS)

    with db.transaction() as conn:
        conn.execute("UPDATE managers SET balance = balance + ?, total_earned = total_earned + ?, "
                    "puzzle_current_design = ? WHERE id=?",
                    (reward, reward, next_design, manager_id))
        conn.execute("INSERT INTO manager_ledger (manager_id, amount, reason) VALUES (?, ?, 'puzzle_completed')",
                    (manager_id, reward))
        conn.execute("INSERT INTO puzzle_completions (manager_id, reward, design_id) VALUES (?, ?, ?)",
                    (manager_id, reward, design_id))
        conn.execute("DELETE FROM puzzle_pieces WHERE manager_id=?", (manager_id,))

    design_name = DESIGNS[design_id]["name"]
    notify(manager_id,
           f"🎉 Картина «{design_name}» собрана полностью! Начислено {reward}G. Она навсегда в твоей коллекции!",
           "/puzzle")

    from .chatbot import announce_puzzle_completed
    winner = query_one("SELECT name FROM managers WHERE id=?", (manager_id,))
    announce_puzzle_completed(winner["name"] if winner else "Менеджер", design_name, reward)


@bp.route("/")
@login_required
def index():
    manager_id = session["manager_id"]
    manager = query_one("SELECT puzzle_current_design FROM managers WHERE id=?", (manager_id,))
    current_design_id = _ensure_current_design(manager_id, manager)
    current_design = DESIGNS[current_design_id]

    my_pieces = query_all("SELECT piece_index FROM puzzle_pieces WHERE manager_id=?", (manager_id,))
    owned_indices = {p["piece_index"] for p in my_pieces}
    pieces = [{"index": i, "owned": i in owned_indices} for i in range(TOTAL_PIECES)]

    completions = query_all(
        "SELECT * FROM puzzle_completions WHERE manager_id=? ORDER BY id DESC LIMIT 10", (manager_id,))
    total_completed = query_one("SELECT COUNT(*) c FROM puzzle_completions WHERE manager_id=?", (manager_id,))["c"]

    leaderboard = query_all("""
        SELECT m.name, COUNT(pc.id) as completions_count, COALESCE(SUM(pc.reward), 0) as total_reward
        FROM managers m
        LEFT JOIN puzzle_completions pc ON pc.manager_id = m.id
        WHERE m.role = 'manager'
        GROUP BY m.id
        HAVING completions_count > 0
        ORDER BY completions_count DESC, total_reward DESC
        LIMIT 10
    """)

    return render_template("puzzle.html",
                          pieces=pieces,
                          owned_count=len(owned_indices),
                          total_pieces=TOTAL_PIECES,
                          current_design=current_design,
                          completions=[dict(c) for c in completions],
                          total_completed=total_completed,
                          leaderboard=[dict(r) for r in leaderboard],
                          reward_min=REWARD_MIN, reward_max=REWARD_MAX,
                          designs=DESIGNS)


@bp.route("/gallery")
@login_required
def gallery():
    manager_id = session["manager_id"]

    rows = query_all("""
        SELECT design_id, COUNT(*) as times_collected, SUM(reward) as total_reward, MAX(completed_at) as last_completed
        FROM puzzle_completions WHERE manager_id=? GROUP BY design_id
    """, (manager_id,))
    collected = {r["design_id"]: dict(r) for r in rows}

    gallery_items = []
    for design_id, design in DESIGNS.items():
        item = {"id": design_id, "name": design["name"], "image": design["image"],
               "unlocked": design_id in collected}
        if design_id in collected:
            item.update(collected[design_id])
        gallery_items.append(item)

    unlocked_count = len(collected)
    return render_template("puzzle_gallery.html",
                          gallery_items=gallery_items,
                          unlocked_count=unlocked_count,
                          total_designs=len(DESIGNS))
