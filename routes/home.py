"""Dashboard: the current match, its four games, and a compact leaderboard."""

from flask import Blueprint, current_app, render_template
from flask_login import login_required

from models import MATCH_ACTIVE, Match
from services.context import get_current_match
from services.scoring import standings

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
@login_required
def index():
    match = get_current_match()
    match_standings = standings(match, current_app.games_config.scoring.placement_points) if match else None
    active_matches = Match.query.filter_by(status=MATCH_ACTIVE).order_by(Match.play_date.desc(), Match.id.desc()).all()
    return render_template("home/index.html", match=match, standings=match_standings, active_matches=active_matches)
