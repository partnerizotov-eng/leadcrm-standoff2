"""Топ менеджеров — статистика и оценка эффективности ("ликвидности")."""
from .db import query_one, query_all, execute


def calculate_manager_stats(manager_id):
    manager = query_one("SELECT * FROM managers WHERE id = ?", (manager_id,))
    if not manager:
        return None

    total_leads = query_one(
        "SELECT COUNT(*) as cnt FROM leads WHERE assigned_manager_id = ?",
        (manager_id,)
    )['cnt']

    converted_leads = query_one("""
        SELECT COUNT(*) as cnt FROM leads
        WHERE assigned_manager_id = ? AND status IN ('submitted', 'approved', 'rejected', 'joined_channel')
    """, (manager_id,))['cnt']

    total_withdrawals = query_one(
        "SELECT COALESCE(SUM(requested_amount), 0) as total FROM withdrawals WHERE manager_id = ?",
        (manager_id,)
    )['total']

    approved_withdrawals = query_one("""
        SELECT COALESCE(SUM(requested_amount), 0) as total FROM withdrawals
        WHERE manager_id = ? AND status = 'completed'
    """, (manager_id,))['total']

    balance = manager['balance'] or 0

    existing = query_one("SELECT id FROM manager_stats WHERE manager_id = ?", (manager_id,))
    if existing:
        execute("""
            UPDATE manager_stats
            SET total_leads = ?, converted_leads = ?, total_withdrawals = ?,
                approved_withdrawals = ?, balance = ?, last_updated = datetime('now')
            WHERE manager_id = ?
        """, (total_leads, converted_leads, total_withdrawals, approved_withdrawals, balance, manager_id))
    else:
        execute("""
            INSERT INTO manager_stats (manager_id, total_leads, converted_leads, total_withdrawals, approved_withdrawals, balance, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """, (manager_id, total_leads, converted_leads, total_withdrawals, approved_withdrawals, balance))

    return {
        'manager_id': manager_id,
        'total_leads': total_leads,
        'converted_leads': converted_leads,
        'total_withdrawals': total_withdrawals,
        'approved_withdrawals': approved_withdrawals,
        'balance': balance
    }


def calculate_liquidity(stats, conversion_rate):
    """Композитная оценка «ликвидности» менеджера (0-100) + рекомендация.
    Учитывает: объём лидов (35%), конверсию (45%), объём выводов (20%).
    Это ориентировочная эвристика для администратора, не строгая метрика."""
    leads = stats['total_leads']
    withdrawals = stats['total_withdrawals']

    if leads == 0:
        return 0.0, "⚪ Нет активности — менеджер ещё не привёл ни одного лида."

    leads_score = min(leads / 30 * 100, 100)
    conversion_score = min(conversion_rate, 100)
    withdrawals_score = min(withdrawals / 500 * 100, 100)

    score = round(leads_score * 0.35 + conversion_score * 0.45 + withdrawals_score * 0.20, 1)

    if score >= 75:
        recommendation = "🟢 Высокая эффективность — можно доверять больше лидов, рассмотреть бонус."
    elif score >= 50:
        recommendation = "🟡 Стабильная работа — держите на текущей нагрузке, наблюдайте динамику."
    elif score >= 25:
        recommendation = "🟠 Есть точки роста — обратите внимание на конверсию и активность."
    else:
        recommendation = "🔴 Низкая эффективность — рекомендуется личная беседа или снижение нагрузки."

    return score, recommendation


def get_all_managers_stats():
    managers = query_all("SELECT * FROM managers WHERE role = 'manager'")
    stats_list = []
    for manager in managers:
        stats = calculate_manager_stats(manager['id'])
        if stats:
            conversion_rate = 0
            if stats['total_leads'] > 0:
                conversion_rate = round((stats['converted_leads'] / stats['total_leads']) * 100, 1)

            liquidity_score, recommendation = calculate_liquidity(stats, conversion_rate)

            stats_list.append({
                'manager': dict(manager),
                'stats': stats,
                'conversion_rate': conversion_rate,
                'liquidity_score': liquidity_score,
                'recommendation': recommendation
            })

    stats_list.sort(key=lambda x: x['stats']['total_leads'], reverse=True)
    return stats_list


def get_top_managers_by_metric(metric='leads', limit=10):
    managers = query_all("SELECT * FROM managers WHERE role = 'manager'")
    results = []
    for manager in managers:
        stats = calculate_manager_stats(manager['id'])
        if stats:
            if metric == 'leads':
                value = stats['total_leads']
            elif metric == 'conversion':
                value = 0
                if stats['total_leads'] > 0:
                    value = (stats['converted_leads'] / stats['total_leads']) * 100
            elif metric == 'withdrawals':
                value = stats['total_withdrawals']
            elif metric == 'balance':
                value = stats['balance']
            elif metric == 'liquidity':
                conversion_rate = 0
                if stats['total_leads'] > 0:
                    conversion_rate = (stats['converted_leads'] / stats['total_leads']) * 100
                value, _ = calculate_liquidity(stats, conversion_rate)
            else:
                value = 0

            results.append({'manager': dict(manager), 'stats': stats, 'value': value})

    results.sort(key=lambda x: x['value'], reverse=True)
    return results[:limit]
