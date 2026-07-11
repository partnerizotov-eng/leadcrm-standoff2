"""Дашборд воронки конверсии — сколько лидов дошло до какого этапа,
с разбивкой по менеджеру, по источнику (группе) и по периоду.

Важная оговорка (честно показываем прямо в шаблоне): lead_status_history
раньше не заполнялась (это исправлено в leads.update_status, см. коммит
рядом), поэтому для старых лидов у нас нет точной истории переходов —
здесь воронка считается по ТЕКУЩЕМУ статусу лида с учётом порядка стадий
(лид со статусом "participated" автоматически считается прошедшим и more
ранние стадии). Это приближение, но оно точнее, чем просто "сколько лидов
сейчас в каждом статусе конкретно" — таким способом более поздние стадии
не занижаются из-за того, что лид уже продвинулся дальше.
"""
from flask import Blueprint, render_template, request

from .db import query_all, query_one
from .security import admin_required

bp = Blueprint("funnel", __name__, url_prefix="/admin")

# Основная цепочка воронки (в порядке прохождения). declined/unresponsive —
# это отдельные терминальные исходы «не дошёл», а не стадия воронки.
FUNNEL_STAGES = ["new", "contacted", "replied", "joined_channel", "participated"]
STAGE_LABELS = {
    "new": "Найден", "contacted": "Написали", "replied": "Ответил",
    "joined_channel": "Вступил в канал", "participated": "Участвовал",
}
DROPOFF_STATUSES = ["declined", "unresponsive"]
STAGE_INDEX = {s: i for i, s in enumerate(FUNNEL_STAGES)}


def _reached_stage_sql(stage_idx):
    """SQL-условие «текущий статус лида означает, что он дошёл минимум до
    этой стадии» — статус либо эта или более поздняя стадия в цепочке,
    либо 'returning' (значит уже participated ранее)."""
    later_or_equal = [s for s, i in STAGE_INDEX.items() if i >= stage_idx]
    statuses = later_or_equal + (["returning"] if stage_idx <= STAGE_INDEX["participated"] else [])
    placeholders = ",".join("?" for _ in statuses)
    return f"status IN ({placeholders})", statuses


@bp.route("/funnel/cohorts")
@admin_required
def cohorts():
    """Когортный анализ: для лидов, найденных в каждом месяце, какой % в
    итоге поучаствовал хотя бы раз (participated/returning) и какой %
    вернулся на второй раз (returning) — простая, но честная метрика
    удержания без внешних библиотек."""
    rows = query_all("""
        SELECT strftime('%Y-%m', found_at) month,
               COUNT(*) total,
               SUM(CASE WHEN status IN ('participated','returning') THEN 1 ELSE 0 END) participated,
               SUM(CASE WHEN status = 'returning' THEN 1 ELSE 0 END) returned
        FROM leads
        WHERE found_at IS NOT NULL
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    """)
    cohorts_data = []
    for r in rows:
        r = dict(r)
        r["participated_pct"] = round(r["participated"] / r["total"] * 100) if r["total"] else 0
        r["returned_pct"] = round(r["returned"] / r["total"] * 100) if r["total"] else 0
        cohorts_data.append(r)
    return render_template("funnel_cohorts.html", cohorts=cohorts_data)


@bp.route("/funnel")
@admin_required
def index():
    days = request.args.get("days", 30, type=int)
    manager_id = request.args.get("manager_id", type=int)
    source_group = request.args.get("source_group", "").strip()

    where, params = ["date(found_at) >= date('now', ?)"], [f"-{days} days"]
    if manager_id:
        where.append("assigned_manager_id = ?")
        params.append(manager_id)
    if source_group:
        where.append("source_group = ?")
        params.append(source_group)
    where_sql = " AND ".join(where)

    total = query_one(f"SELECT COUNT(*) c FROM leads WHERE {where_sql}", params)["c"]

    stages = []
    for stage in FUNNEL_STAGES:
        if STAGE_INDEX[stage] == 0:
            # Первая стадия — «найден» — по определению равна всем лидам,
            # независимо от того, чем всё закончилось (даже declined/
            # unresponsive когда-то были найдены). Иначе первый бар
            # выглядел бы <100%, что визуально сбивает с толку.
            count = total
        else:
            cond, statuses = _reached_stage_sql(STAGE_INDEX[stage])
            count = query_one(
                f"SELECT COUNT(*) c FROM leads WHERE {where_sql} AND {cond}",
                params + statuses)["c"]
        pct_of_total = round(count / total * 100) if total else 0
        stages.append({"key": stage, "label": STAGE_LABELS[stage], "count": count, "pct": pct_of_total})

    # процент перехода между соседними стадиями (не от общего, а от предыдущей)
    for i, s in enumerate(stages):
        if i == 0:
            s["pct_of_prev"] = 100
        else:
            prev = stages[i - 1]["count"]
            s["pct_of_prev"] = round(s["count"] / prev * 100) if prev else 0

    dropoffs = []
    for status in DROPOFF_STATUSES:
        count = query_one(f"SELECT COUNT(*) c FROM leads WHERE {where_sql} AND status=?",
                           params + [status])["c"]
        dropoffs.append({"key": status, "count": count,
                          "pct": round(count / total * 100) if total else 0})

    by_manager = query_all(f"""
        SELECT m.id, m.name,
          COUNT(l.id) total,
          SUM(CASE WHEN l.status IN ('participated','returning') THEN 1 ELSE 0 END) converted
        FROM managers m LEFT JOIN leads l ON l.assigned_manager_id = m.id AND {where_sql}
        WHERE m.role='manager'
        GROUP BY m.id ORDER BY converted DESC
    """, params)
    by_manager = [dict(r) for r in by_manager]
    for r in by_manager:
        r["pct"] = round(r["converted"] / r["total"] * 100) if r["total"] else 0

    by_source = query_all(f"""
        SELECT COALESCE(NULLIF(source_group, ''), '(не указан)') AS source_group,
          COUNT(*) total,
          SUM(CASE WHEN status IN ('participated','returning') THEN 1 ELSE 0 END) converted
        FROM leads WHERE {where_sql}
        GROUP BY source_group ORDER BY total DESC
    """, params)
    by_source = [dict(r) for r in by_source]
    for r in by_source:
        r["pct"] = round(r["converted"] / r["total"] * 100) if r["total"] else 0

    managers = query_all("SELECT id, name FROM managers WHERE role='manager' ORDER BY name")
    source_groups = query_all("SELECT DISTINCT source_group FROM leads WHERE source_group != '' ORDER BY source_group")

    return render_template(
        "funnel.html",
        total=total, stages=stages, dropoffs=dropoffs,
        by_manager=by_manager, by_source=by_source,
        days=days, manager_id=manager_id, source_group=source_group,
        managers=[dict(m) for m in managers],
        source_groups=[r["source_group"] for r in source_groups],
    )
