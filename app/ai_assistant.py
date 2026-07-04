"""AI-помощник для менеджеров"""
import json
import re
from datetime import datetime, timedelta
from flask import Blueprint, render_template, session, request, jsonify
from .db import query_one, query_all
from .security import login_required

bp = Blueprint("ai", __name__, url_prefix="/ai")

class AIAssistant:
    """Умный помощник для менеджеров"""
    
    def __init__(self, manager_id):
        self.manager_id = manager_id
        self.load_manager_data()
    
    def load_manager_data(self):
        """Загрузка данных менеджера"""
        # Статистика
        self.stats = query_one("""
            SELECT 
                COUNT(DISTINCT l.id) as total_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'new' THEN l.id END) as new_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'contacted' THEN l.id END) as contacted_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'replied' THEN l.id END) as replied_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'participated' THEN l.id END) as participated_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'returning' THEN l.id END) as returning_leads,
                COUNT(DISTINCT CASE WHEN l.status IN ('declined', 'unresponsive') THEN l.id END) as lost_leads,
                COALESCE(ROUND(CAST(COUNT(DISTINCT CASE WHEN l.status IN ('participated', 'returning') THEN l.id END) AS REAL) / 
                NULLIF(COUNT(DISTINCT l.id), 0) * 100, 1), 0) as conversion_pct
            FROM managers m
            LEFT JOIN leads l ON l.assigned_manager_id = m.id
            WHERE m.id = ?
        """, (self.manager_id,))
        
        # Недавние лиды
        self.recent_leads = query_all("""
            SELECT id, name, vk_id, status, found_at AS created_at 
            FROM leads 
            WHERE assigned_manager_id = ? 
            ORDER BY found_at DESC 
            LIMIT 10
        """, (self.manager_id,))
        
        # Статус сегодняшних задач
        today = datetime.now().date().isoformat()
        self.today_tasks = query_one("""
            SELECT 
                COUNT(DISTINCT l.id) as today_leads,
                COUNT(DISTINCT CASE WHEN l.status = 'new' THEN l.id END) as new_today,
                COUNT(DISTINCT s.id) as today_submissions
            FROM managers m
            LEFT JOIN leads l ON l.assigned_manager_id = m.id AND DATE(l.found_at) = ?
            LEFT JOIN submissions s ON s.manager_id = m.id AND DATE(s.created_at) = ?
            WHERE m.id = ?
        """, (today, today, self.manager_id))
    
    def get_smart_recommendations(self):
        """Умные рекомендации"""
        recommendations = []
        
        # Рекомендация: новые лиды
        if self.stats and self.stats["new_leads"] > 0:
            recommendations.append({
                "type": "action",
                "priority": "high",
                "title": f"📋 {self.stats['new_leads']} новых лидов ждут вашего внимания",
                "description": "Начните общение с новыми лидами, чтобы повысить конверсию",
                "action": "/leads?status=new",
                "action_text": "Перейти к новым лидам"
            })
        
        # Рекомендация: лиды без контакта
        old_leads = query_one("""
            SELECT COUNT(*) as c 
            FROM leads 
            WHERE assigned_manager_id = ? 
            AND status = 'new' 
            AND DATE(found_at) < DATE('now', '-3 days')
        """, (self.manager_id,))
        
        if old_leads and old_leads["c"] > 0:
            recommendations.append({
                "type": "warning",
                "priority": "high",
                "title": f"⚠️ {old_leads['c']} лидов ждут более 3 дней",
                "description": "Свяжитесь с ними сегодня, чтобы не потерять интерес",
                "action": "/leads?status=new",
                "action_text": "Посмотреть"
            })
        
        # Рекомендация: конверсия
        if self.stats and self.stats["conversion_pct"] < 30:
            recommendations.append({
                "type": "tip",
                "priority": "medium",
                "title": "🎯 Низкая конверсия",
                "description": f"Ваша конверсия {self.stats['conversion_pct']}%. Попробуйте изменить подход или использовать другие скрипты",
                "action": "/scripts",
                "action_text": "Проверить скрипты"
            })
        
        # Рекомендация: отправка заявок
        if self.today_tasks and self.today_tasks["today_submissions"] == 0:
            recommendations.append({
                "type": "action",
                "priority": "medium",
                "title": "📸 Сегодня нет заявок на проверку",
                "description": "Отправьте хотя бы одну заявку, чтобы заработать голду",
                "action": "/leads",
                "action_text": "К лидам"
            })
        
        # Рекомендация: лучший скрипт
        best_script = query_one("""
            SELECT s.label, 
                   COUNT(o.id) as uses,
                   SUM(CASE WHEN o.response = 'replied' THEN 1 ELSE 0 END) as replies,
                   COALESCE(ROUND(CAST(SUM(CASE WHEN o.response = 'replied' THEN 1 ELSE 0 END) AS REAL) / 
                   NULLIF(COUNT(o.id), 0) * 100, 1), 0) as conversion
            FROM scripts s
            JOIN outreach_log o ON o.script_id = s.id
            WHERE o.manager_id = ?
            GROUP BY s.id
            HAVING uses > 3
            ORDER BY conversion DESC
            LIMIT 1
        """, (self.manager_id,))
        
        if best_script and best_script["conversion"] > 50:
            recommendations.append({
                "type": "success",
                "priority": "low",
                "title": f"📝 Лучший скрипт: {best_script['label']}",
                "description": f"Конверсия {best_script['conversion']}% ({best_script['replies']} ответов из {best_script['uses']})",
                "action": "/scripts",
                "action_text": "Посмотреть скрипты"
            })
        
        # Рекомендация: регулярные игроки
        returning = query_one("""
            SELECT COUNT(*) as c 
            FROM leads 
            WHERE assigned_manager_id = ? 
            AND status = 'returning'
        """, (self.manager_id,))
        
        if returning and returning["c"] > 0:
            recommendations.append({
                "type": "info",
                "priority": "medium",
                "title": f"🔄 {returning['c']} постоянных игроков",
                "description": "Поддерживайте связь с ними, они приносят больше всего голды",
                "action": "/leads?status=returning",
                "action_text": "К постоянным игрокам"
            })
        
        return recommendations
    
    def get_best_time_to_contact(self):
        """Определение лучшего времени для контакта"""
        # Анализ истории ответов
        responses = query_all("""
            SELECT strftime('%H', created_at) as hour,
                   COUNT(*) as total,
                   SUM(CASE WHEN response = 'replied' THEN 1 ELSE 0 END) as replies
            FROM outreach_log
            WHERE manager_id = ? AND response != 'pending'
            GROUP BY hour
            ORDER BY replies DESC
        """, (self.manager_id,))
        
        if responses:
            best_hour = responses[0]["hour"]
            return {
                "hour": f"{best_hour}:00",
                "success_rate": round(responses[0]["replies"] / responses[0]["total"] * 100, 1),
                "total_contacts": responses[0]["total"]
            }
        
        return {"hour": "20:00", "success_rate": 0, "total_contacts": 0}
    
    def get_next_steps(self):
        """Рекомендация следующих шагов"""
        steps = []
        
        # Шаг 1: Проверить новые лиды
        if self.stats and self.stats["new_leads"] > 0:
            steps.append({
                "order": 1,
                "action": "Напишите новым лидам",
                "details": f"Осталось {self.stats['new_leads']} новых лидов",
                "priority": "Высокий"
            })
        
        # Шаг 2: Отправить заявки
        if self.today_tasks and self.today_tasks["today_submissions"] < 3:
            steps.append({
                "order": 2,
                "action": "Отправьте заявки на проверку",
                "details": "Сделайте скриншоты участия лидов",
                "priority": "Средний"
            })
        
        # Шаг 3: Работа с постоянными
        if self.stats and self.stats["returning_leads"] > 0:
            steps.append({
                "order": 3,
                "action": "Поддерживайте связь с постоянными",
                "details": f"{self.stats['returning_leads']} возвращающихся лидов",
                "priority": "Средний"
            })
        
        # Шаг 4: Поиск новых
        if self.stats and self.stats["total_leads"] < 20:
            steps.append({
                "order": 4,
                "action": "Найдите новых лидов",
                "description": "Проверьте новые группы Standoff 2",
                "priority": "Низкий"
            })
        
        return steps

@bp.route("/")
@login_required
def index():
    """Страница AI-помощника"""
    manager_id = session["manager_id"]
    assistant = AIAssistant(manager_id)
    
    recommendations = assistant.get_smart_recommendations()
    best_time = assistant.get_best_time_to_contact()
    steps = assistant.get_next_steps()
    
    return render_template("ai_assistant.html",
                          recommendations=recommendations,
                          best_time=best_time,
                          steps=steps,
                          stats=assistant.stats)

@bp.route("/recommendations")
@login_required
def get_recommendations():
    """API для получения рекомендаций"""
    manager_id = session["manager_id"]
    assistant = AIAssistant(manager_id)
    return jsonify(assistant.get_smart_recommendations())

@bp.route("/insights")
@login_required
def get_insights():
    """Получение инсайтов по лидам"""
    manager_id = session["manager_id"]
    
    # Анализ лидов
    insights = query_one("""
        SELECT 
            COUNT(DISTINCT l.id) as total,
            COUNT(DISTINCT CASE WHEN DATE(l.found_at) = DATE('now') THEN l.id END) as today,
            COUNT(DISTINCT CASE WHEN DATE(l.found_at) >= DATE('now', '-7 days') THEN l.id END) as week,
            COUNT(DISTINCT CASE WHEN l.status = 'new' THEN l.id END) as "new",
            COUNT(DISTINCT CASE WHEN l.status = 'contacted' THEN l.id END) as contacted,
            COUNT(DISTINCT CASE WHEN l.status = 'replied' THEN l.id END) as replied,
            COUNT(DISTINCT CASE WHEN l.status = 'participated' THEN l.id END) as participated,
            COUNT(DISTINCT CASE WHEN l.status = 'returning' THEN l.id END) as "returning",
            COALESCE(ROUND(CAST(COUNT(DISTINCT CASE WHEN l.status IN ('participated', 'returning') THEN l.id END) AS REAL) / 
            NULLIF(COUNT(DISTINCT l.id), 0) * 100, 1), 0) as conversion
        FROM managers m
        LEFT JOIN leads l ON l.assigned_manager_id = m.id
        WHERE m.id = ?
    """, (manager_id,))
    
    return jsonify(dict(insights) if insights else {})