"""Скоринг риска / детект дублей.

Важная честная оговорка: это НЕ полноценный антифрод-движок — для этого
нужны IP/девайс-трекинг и внешние данные, которых в проекте пока нет.
Это набор эвристик поверх того, что реально есть в базе:

  - переиспользованные скриншоты (один и тот же файл в нескольких заявках)
  - лиды-почти-дубли (тот же vk_id в другом регистре — проскочили мимо
    UNIQUE-ограничения, потому что extract_id не приводит к нижнему регистру)
  - менеджеры с аномально высоким % одобрения заявок относительно среднего
  - всплески добавления лидов за короткое окно (похоже на скрипт/бота)

Каждый флаг — повод для РУЧНОЙ проверки админом, не автоматическое решение
и не наказание. Ничего не блокирует и не меняет — только читает.
"""
import hashlib
from collections import defaultdict
from datetime import datetime

from .db import query_all


def _upload_path(filename):
    from config import DATA_DIR
    return DATA_DIR / "uploads" / filename


def find_duplicate_screenshots(limit=500):
    rows = query_all("""
        SELECT s.id, s.screenshot, s.lead_id, s.manager_id, s.created_at,
               l.name lead_name, m.name manager_name
        FROM submissions s
        LEFT JOIN leads l ON l.id = s.lead_id
        LEFT JOIN managers m ON m.id = s.manager_id
        WHERE s.screenshot != ''
        ORDER BY s.created_at DESC
        LIMIT ?
    """, (limit,))
    by_hash = defaultdict(list)
    for r in rows:
        path = _upload_path(r["screenshot"])
        try:
            data = path.read_bytes()
        except OSError:
            continue
        h = hashlib.sha256(data).hexdigest()
        by_hash[h].append(dict(r))
    return [group for group in by_hash.values() if len(group) > 1]


def find_case_duplicate_leads():
    rows = query_all("SELECT id, vk_id, name, assigned_manager_id, found_at FROM leads")
    by_lower = defaultdict(list)
    for r in rows:
        by_lower[r["vk_id"].lower()].append(dict(r))
    return [group for group in by_lower.values() if len(group) > 1]


def find_manager_approval_outliers(min_submissions=5, threshold_pp=25):
    rows = query_all("""
        SELECT manager_id, m.name,
          COUNT(*) total,
          SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) approved
        FROM submissions s JOIN managers m ON m.id = s.manager_id
        GROUP BY manager_id HAVING COUNT(*) >= ?
    """, (min_submissions,))
    data = [dict(r) for r in rows]
    for r in data:
        r["approval_pct"] = round(r["approved"] / r["total"] * 100) if r["total"] else 0
    if not data:
        return []
    avg = sum(r["approval_pct"] for r in data) / len(data)
    return [r for r in data if r["approval_pct"] - avg >= threshold_pp]


def find_rapid_lead_bursts(window_minutes=10, min_count=8):
    rows = query_all("""
        SELECT assigned_manager_id manager_id, m.name, found_at
        FROM leads l JOIN managers m ON m.id = l.assigned_manager_id
        WHERE found_at IS NOT NULL
        ORDER BY assigned_manager_id, found_at
    """)
    by_manager = defaultdict(list)
    for r in rows:
        by_manager[(r["manager_id"], r["name"])].append(r["found_at"])

    bursts = []
    for (mid, name), times in by_manager.items():
        parsed = []
        for t in times:
            try:
                parsed.append(datetime.fromisoformat(t))
            except ValueError:
                continue
        parsed.sort()
        i = 0
        for j in range(len(parsed)):
            while (parsed[j] - parsed[i]).total_seconds() > window_minutes * 60:
                i += 1
            if j - i + 1 >= min_count:
                bursts.append({
                    "manager_id": mid, "name": name,
                    "count": j - i + 1, "window_minutes": window_minutes,
                    "from": parsed[i].isoformat(timespec="minutes"),
                    "to": parsed[j].isoformat(timespec="minutes"),
                })
                break  # одного флага на менеджера достаточно, не спамим
    return bursts


def compute_risk_report():
    return {
        "duplicate_screenshots": find_duplicate_screenshots(),
        "case_duplicate_leads": find_case_duplicate_leads(),
        "approval_outliers": find_manager_approval_outliers(),
        "rapid_bursts": find_rapid_lead_bursts(),
    }
