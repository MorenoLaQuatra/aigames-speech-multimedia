"""Matches: create, pick the current one, manage teams, correct scores,
finish/reopen single games, archive, and show results (normal page,
full-screen projector view, full-screen results of one game)."""

from datetime import date, datetime, timezone

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import DateField, FloatField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from extensions import db
from i18n import t
from models import MATCH_ACTIVE, MATCH_ARCHIVED, TEAM_COLORS, Match, ScoreEvent, Team
from routes.games import GAMES, GAMES_BY_SLUG
from services.context import clear_current_match, get_current_match, set_current_match
from services.media import delete_match_media
from services.scoring import GAME_SLUGS, add_score, finish_game, reopen_game, standings, standings_json

matches_bp = Blueprint("matches", __name__, url_prefix="/matches")

MAX_TEAMS = len(TEAM_COLORS)
ARCHIVE_PAGE_SIZE = 30


class MatchForm(FlaskForm):
    name = StringField(validators=[DataRequired(), Length(max=120)])
    school = StringField(validators=[Optional(), Length(max=160)])
    play_date = DateField(validators=[DataRequired()])
    notes = TextAreaField(validators=[Optional(), Length(max=2000)])
    teams = TextAreaField(validators=[DataRequired()])


class TeamForm(FlaskForm):
    name = StringField(validators=[DataRequired(), Length(max=80)])


class AdjustForm(FlaskForm):
    team_id = SelectField(coerce=int, validators=[DataRequired()])
    game = SelectField(choices=[(g, g) for g in GAME_SLUGS], validators=[DataRequired()])
    points = FloatField(validators=[DataRequired()])
    reason = StringField(validators=[Optional(), Length(max=200)])


def _get_match(match_id):
    match = db.session.get(Match, match_id)
    if match is None:
        abort(404)
    return match


def _require_editable(match):
    if match.is_archived:
        flash(t("matches.archived_readonly"), "error")
        return False
    return True


def _parse_team_names(text):
    names = []
    for line in text.splitlines():
        name = line.strip()[:80]
        if name and name.lower() not in [n.lower() for n in names]:
            names.append(name)
    return names


# ---------------------------------------------------------------- list/create

@matches_bp.route("/")
@login_required
def index():
    query = request.args.get("q", "").strip()
    archived = Match.query.filter_by(status=MATCH_ARCHIVED)
    if query:
        like = f"%{query}%"
        archived = archived.filter(db.or_(Match.name.ilike(like), Match.school.ilike(like)))
    archived = archived.order_by(Match.play_date.desc(), Match.id.desc()).limit(ARCHIVE_PAGE_SIZE).all()
    active = Match.query.filter_by(status=MATCH_ACTIVE).order_by(Match.play_date.desc(), Match.id.desc()).all()

    form = MatchForm()
    form.play_date.data = date.today()
    form.teams.data = "\n".join(t(f"matches.default_team_{i}") for i in range(1, 5))
    return render_template("matches/index.html", active=active, archived=archived, query=query, form=form,
                           max_teams=MAX_TEAMS)


@matches_bp.route("/new", methods=["POST"])
@login_required
def create():
    form = MatchForm()
    names = _parse_team_names(form.teams.data or "")
    if not form.validate_on_submit() or not names:
        flash(t("matches.create_invalid"), "error")
        return redirect(url_for("matches.index"))
    if len(names) > MAX_TEAMS:
        flash(t("matches.too_many_teams", n=MAX_TEAMS), "error")
        return redirect(url_for("matches.index"))

    match = Match(
        name=form.name.data.strip(),
        school=(form.school.data or "").strip(),
        play_date=form.play_date.data,
        notes=(form.notes.data or "").strip(),
        created_by_id=current_user.id,
    )
    for position, name in enumerate(names):
        match.teams.append(Team(name=name, color=TEAM_COLORS[position], position=position))
    db.session.add(match)
    db.session.commit()
    set_current_match(match)
    flash(t("matches.created", name=match.name), "success")
    return redirect(url_for("home.index"))


# --------------------------------------------------------------------- detail

@matches_bp.route("/<int:match_id>")
@login_required
def detail(match_id):
    match = _get_match(match_id)
    events = (ScoreEvent.query.filter_by(match_id=match.id)
              .order_by(ScoreEvent.created_at.desc()).limit(200).all())
    adjust_form = AdjustForm()
    adjust_form.team_id.choices = [(team.id, team.name) for team in match.teams]
    adjust_form.game.choices = [(g["slug"], t(f"games.{g['slug']}.title")) for g in GAMES]
    return render_template("matches/detail.html", match=match, events=events, adjust_form=adjust_form,
                           team_form=TeamForm(), max_teams=MAX_TEAMS,
                           is_current=(get_current_match() is not None and get_current_match().id == match.id))


@matches_bp.route("/<int:match_id>/select", methods=["POST"])
@login_required
def select(match_id):
    match = _get_match(match_id)
    if not _require_editable(match):
        return redirect(url_for("matches.detail", match_id=match.id))
    set_current_match(match)
    flash(t("matches.now_current", name=match.name), "success")
    return redirect(url_for("home.index"))


@matches_bp.route("/<int:match_id>/edit", methods=["POST"])
@login_required
def edit(match_id):
    match = _get_match(match_id)
    if not _require_editable(match):
        return redirect(url_for("matches.detail", match_id=match.id))
    name = request.form.get("name", "").strip()[:120]
    if not name:
        flash(t("matches.name_required"), "error")
        return redirect(url_for("matches.detail", match_id=match.id))
    match.name = name
    match.school = request.form.get("school", "").strip()[:160]
    match.notes = request.form.get("notes", "").strip()[:2000]
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("matches.detail", match_id=match.id))


@matches_bp.route("/<int:match_id>/archive", methods=["POST"])
@login_required
def archive(match_id):
    match = _get_match(match_id)
    if match.is_archived:
        return redirect(url_for("matches.detail", match_id=match.id))
    match.status = MATCH_ARCHIVED
    match.archived_at = datetime.now(timezone.utc)
    db.session.commit()
    if current_app.games_config.privacy.delete_media_on_archive:
        _forget_match_media(match)
    if get_current_match() is None or get_current_match().id == match.id:
        clear_current_match()
    flash(t("matches.archived", name=match.name), "success")
    return redirect(url_for("matches.results", match_id=match.id))


def _forget_match_media(match):
    """Delete recordings/clips/images on disk and clear the DB paths to them."""
    from models import DrawingAttempt, VoiceClip, VoiceVolunteer

    delete_match_media(match.id)
    VoiceVolunteer.query.filter_by(match_id=match.id).update({"reference_path": None})
    VoiceClip.query.filter_by(match_id=match.id).update({"audio_path": None})
    DrawingAttempt.query.filter_by(match_id=match.id).update({"image_path": None})
    db.session.commit()


@matches_bp.route("/<int:match_id>/reopen", methods=["POST"])
@login_required
def reopen(match_id):
    if not current_user.is_admin:
        abort(403)
    match = _get_match(match_id)
    match.status = MATCH_ACTIVE
    match.archived_at = None
    db.session.commit()
    flash(t("matches.reopened", name=match.name), "success")
    return redirect(url_for("matches.detail", match_id=match.id))


@matches_bp.route("/<int:match_id>/delete", methods=["POST"])
@login_required
def delete(match_id):
    if not current_user.is_admin:
        abort(403)
    from models import DrawingAttempt, VoiceClip, VoiceGuess, VoiceVolunteer

    match = _get_match(match_id)
    delete_match_media(match.id)
    clip_ids = [c.id for c in VoiceClip.query.filter_by(match_id=match.id)]
    if clip_ids:
        VoiceGuess.query.filter(VoiceGuess.clip_id.in_(clip_ids)).delete(synchronize_session=False)
    VoiceClip.query.filter_by(match_id=match.id).delete()
    VoiceVolunteer.query.filter_by(match_id=match.id).delete()
    DrawingAttempt.query.filter_by(match_id=match.id).delete()
    ScoreEvent.query.filter_by(match_id=match.id).delete()
    name = match.name
    db.session.delete(match)
    db.session.commit()
    flash(t("matches.deleted", name=name), "success")
    return redirect(url_for("matches.index"))


# ---------------------------------------------------------------------- teams

@matches_bp.route("/<int:match_id>/teams/add", methods=["POST"])
@login_required
def add_team(match_id):
    match = _get_match(match_id)
    form = TeamForm()
    if not _require_editable(match):
        return redirect(url_for("matches.detail", match_id=match.id))
    if not form.validate_on_submit():
        flash(t("matches.team_name_required"), "error")
    elif len(match.teams) >= MAX_TEAMS:
        flash(t("matches.too_many_teams", n=MAX_TEAMS), "error")
    else:
        used = {team.color for team in match.teams}
        color = next(c for c in TEAM_COLORS if c not in used)
        position = max((team.position for team in match.teams), default=-1) + 1
        db.session.add(Team(match_id=match.id, name=form.name.data.strip(), color=color, position=position))
        db.session.commit()
        flash(t("common.saved"), "success")
    return redirect(url_for("matches.detail", match_id=match.id))


@matches_bp.route("/<int:match_id>/teams/<int:team_id>/rename", methods=["POST"])
@login_required
def rename_team(match_id, team_id):
    match = _get_match(match_id)
    team = Team.query.filter_by(id=team_id, match_id=match.id).first_or_404()
    form = TeamForm()
    if _require_editable(match) and form.validate_on_submit():
        team.name = form.name.data.strip()
        db.session.commit()
        flash(t("common.saved"), "success")
    return redirect(url_for("matches.detail", match_id=match.id))


@matches_bp.route("/<int:match_id>/teams/<int:team_id>/delete", methods=["POST"])
@login_required
def delete_team(match_id, team_id):
    match = _get_match(match_id)
    team = Team.query.filter_by(id=team_id, match_id=match.id).first_or_404()
    if not _require_editable(match):
        return redirect(url_for("matches.detail", match_id=match.id))
    if ScoreEvent.query.filter_by(team_id=team.id).first() is not None:
        flash(t("matches.team_has_scores"), "error")
        return redirect(url_for("matches.detail", match_id=match.id))
    from models import DrawingAttempt, VoiceVolunteer

    if VoiceVolunteer.query.filter_by(team_id=team.id).first() or DrawingAttempt.query.filter_by(team_id=team.id).first():
        flash(t("matches.team_has_scores"), "error")
        return redirect(url_for("matches.detail", match_id=match.id))
    db.session.delete(team)
    db.session.commit()
    flash(t("common.deleted"), "success")
    return redirect(url_for("matches.detail", match_id=match.id))


# --------------------------------------------------------------------- scores

@matches_bp.route("/<int:match_id>/scores/adjust", methods=["POST"])
@login_required
def adjust_score(match_id):
    match = _get_match(match_id)
    form = AdjustForm()
    form.team_id.choices = [(team.id, team.name) for team in match.teams]
    form.game.choices = [(g, g) for g in GAME_SLUGS]
    if not _require_editable(match):
        return redirect(url_for("matches.detail", match_id=match.id))
    if not form.validate_on_submit() or form.points.data == 0:
        flash(t("matches.adjust_invalid"), "error")
        return redirect(url_for("matches.detail", match_id=match.id))
    team = Team.query.filter_by(id=form.team_id.data, match_id=match.id).first_or_404()
    add_score(match, team, form.game.data, form.points.data, current_user,
              detail={"kind": "manual", "reason": (form.reason.data or "").strip()})
    flash(t("matches.adjusted"), "success")
    next_path = request.form.get("next", "")
    if next_path.startswith("/") and not next_path.startswith("//"):
        return redirect(next_path)
    return redirect(url_for("matches.detail", match_id=match.id))


@matches_bp.route("/<int:match_id>/scores/<int:event_id>/delete", methods=["POST"])
@login_required
def delete_score(match_id, event_id):
    match = _get_match(match_id)
    event = ScoreEvent.query.filter_by(id=event_id, match_id=match.id).first_or_404()
    if _require_editable(match):
        db.session.delete(event)
        db.session.commit()
        flash(t("matches.score_deleted"), "success")
    return redirect(url_for("matches.detail", match_id=match.id))


# ---------------------------------------------------------------- game finish

def _check_game(game):
    if game not in GAMES_BY_SLUG:
        abort(404)


@matches_bp.route("/<int:match_id>/games/<game>/finish", methods=["POST"])
@login_required
def finish(match_id, game):
    """Close one game: its points are locked and its results go on screen."""
    match = _get_match(match_id)
    _check_game(game)
    if not _require_editable(match):
        return redirect(url_for("matches.detail", match_id=match.id))
    finish_game(match, game, current_user)
    flash(t("game.finished_flash", game=t(f"games.{game}.title")), "success")
    return redirect(url_for("matches.game_display", match_id=match.id, game=game))


@matches_bp.route("/<int:match_id>/games/<game>/reopen", methods=["POST"])
@login_required
def reopen_game_route(match_id, game):
    match = _get_match(match_id)
    _check_game(game)
    if not _require_editable(match):
        return redirect(url_for("matches.detail", match_id=match.id))
    reopen_game(match, game)
    flash(t("game.reopened_flash", game=t(f"games.{game}.title")), "success")
    return redirect(url_for(f"{game}.play"))


# -------------------------------------------------------------------- results

@matches_bp.route("/<int:match_id>/results")
@login_required
def results(match_id):
    match = _get_match(match_id)
    data = standings(match, current_app.games_config.scoring.placement_points)
    return render_template("matches/results.html", match=match, standings=data,
                           placement_points=current_app.games_config.scoring.placement_points)


@matches_bp.route("/<int:match_id>/display")
@login_required
def display(match_id):
    match = _get_match(match_id)
    page_config = {
        "url": url_for("matches.api_standings", match_id=match.id),
        "refreshMs": 5000,
        "games": [{"slug": g["slug"], "icon": g["icon"], "title": t(f"games.{g['slug']}.title")} for g in GAMES],
        "strings": {"points": t("results.points_short"), "notPlayed": t("results.not_played")},
    }
    return render_template("matches/display.html", match=match, page_config=page_config)


@matches_bp.route("/<int:match_id>/games/<game>/display")
@login_required
def game_display(match_id, game):
    """Full-screen results of one game: rank, points in the game and the
    placement points it gives towards the final ranking (10/8/6/4)."""
    match = _get_match(match_id)
    _check_game(game)
    placement_points = current_app.games_config.scoring.placement_points
    page_config = {
        "url": url_for("matches.api_standings", match_id=match.id),
        "game": game,
        "strings": {"points": t("results.points_short"), "notPlayed": t("results.not_played")},
    }
    return render_template("matches/game_display.html", match=match, game=GAMES_BY_SLUG[game],
                           page_config=page_config,
                           placement_text=" / ".join(str(p) for p in placement_points),
                           back_url=url_for(f"{game}.play") if not match.is_archived
                           else url_for("matches.results", match_id=match.id))


@matches_bp.route("/<int:match_id>/api/standings")
@login_required
def api_standings(match_id):
    match = _get_match(match_id)
    return jsonify(standings_json(match, current_app.games_config.scoring.placement_points))
