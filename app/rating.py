from flask import Blueprint, render_template

bp = Blueprint("rating", __name__)

@bp.route("/rating")
def index():
    return "<h1>🏆 Рейтинг</h1><p>Страница рейтинга в разработке</p>"
