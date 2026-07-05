"""Payouts — public transparency feed of fully confirmed withdrawals.
Visible to every logged-in manager (not just the owner), so the team can
see that payouts genuinely happen and admin backs them with a screenshot.
"""
from flask import Blueprint, render_template
from .db import query_all
from .security import login_required

bp = Blueprint("payouts", __name__)


@bp.route("/payouts")
@login_required
def index():
    rows = query_all("""
        SELECT w.*, m.name manager_name
        FROM withdrawals w
        JOIN managers m ON m.id = w.manager_id
        WHERE w.payout_admin_confirmed = 1
        ORDER BY w.updated_at DESC
        LIMIT 200
    """)
    return render_template("payouts.html", payouts=[dict(r) for r in rows])
