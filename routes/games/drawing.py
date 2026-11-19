"""Game 3 - Visual Taboo (drawing).

A team gets a scene and a list of elements to make appear, and describes
the scene without the forbidden words. The image worker translates the
description (it -> en), draws it, and runs an open-vocabulary detector for
each element. Each element found is worth games.drawing.points_per_element;
the instructor can override the detector before confirming the score. A team
has games.drawing.attempts_per_team attempts per scene; confirming again
replaces the previous score for that scene (ScoreEvent ref).
"""

import base64
import json
import time

import requests
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from extensions import db
from i18n import get_locale, t
from models import DrawingAttempt, DrawingChallenge, Team
from services.context import admin_required, get_current_match, require_current_match
from services.forbidden_words import find_forbidden
from services.media import is_inside_media_dir, new_media_path
from services.model_manager import WorkerUnavailable
from services.scoring import add_score, ensure_open

drawing_bp = Blueprint("drawing", __name__, url_prefix="/games/drawing")

WORKER = "image_gen"


def _cfg():
    return current_app.games_config.games.drawing


def _image_model_cfg():
    """Settings of the selected text-to-image model (games.drawing.image_models)."""
    cfg = _cfg()
    return cfg.image_models[cfg.image_model]


def _api_error(message, status, **extra):
    return jsonify({"error": message, **extra}), status


def _challenge_dict(challenge):
    locale = get_locale()
    return {
        "id": challenge.id,
        "title": getattr(challenge, f"title_{locale}"),
        "brief": getattr(challenge, f"brief_{locale}"),
        "elements": [{"label": el[locale], "it": el["it"], "en": el["en"]} for el in challenge.elements],
        "forbidden": challenge.forbidden_list,
    }


def _attempt_dict(attempt):
    detections = attempt.detections
    confirmed = attempt.confirmed
    elements = []
    for index, element in enumerate(attempt.challenge.elements):
        det = detections[str(index)]
        elements.append({
            "label": element[get_locale()],
            "found": det["found"],
            "score": det["score"],
            "box": det["box"],
            "confirmed": None if confirmed is None else index in confirmed,
        })
    return {
        "id": attempt.id,
        "team_id": attempt.team_id,
        "challenge_id": attempt.challenge_id,
        "prompt": attempt.prompt_text,
        "translated": attempt.translated_text,
        "image_url": url_for("drawing.image", attempt_id=attempt.id) if attempt.image_path else None,
        "elements": elements,
        "is_confirmed": confirmed is not None,
        "points": None if confirmed is None else len(confirmed) * _cfg().points_per_element,
    }


def _team_in_match(match, team_id):
    team = Team.query.filter_by(id=team_id, match_id=match.id).first()
    if team is None:
        abort(404)
    return team


# ---------------------------------------------------------------------- play

@drawing_bp.route("/")
@login_required
@require_current_match
def play(match):
    cfg = _cfg()
    challenges = DrawingChallenge.query.filter_by(active=True).order_by(DrawingChallenge.id).all()
    page_config = {
        "matchId": match.id,
        "challenges": [_challenge_dict(c) for c in challenges],
        "attemptsPerTeam": cfg.attempts_per_team,
        "pointsPerElement": cfg.points_per_element,
        "maxPromptChars": cfg.max_prompt_chars,
        "urls": {
            "attempt": url_for("drawing.api_attempt"),
            "attempts": url_for("drawing.api_attempts"),
            "confirm": url_for("drawing.api_confirm", attempt_id=0).replace("/0/", "/__ID__/"),
        },
        "strings": {key.split(".", 1)[1]: value for key, value in _js_strings().items()},
    }
    image_model = _image_model_cfg()
    return render_template("games/drawing.html", match=match, page_config=page_config,
                           has_challenges=bool(challenges), turn_seconds=cfg.turn_seconds,
                           translates=image_model.translate_prompt, image_credit=image_model.credit)


def _js_strings():
    keys = [
        "drawing.forbidden_live", "drawing.generating", "drawing.generated_in", "drawing.attempts_left",
        "drawing.no_attempts_left", "drawing.found", "drawing.not_found", "drawing.confirm",
        "drawing.reconfirm", "drawing.confirmed", "drawing.points_awarded", "drawing.chars_left",
        "drawing.attempt_n", "drawing.empty_prompt", "drawing.score_label", "model.not_ready",
    ]
    return {key: t(key) for key in keys}


@drawing_bp.route("/api/attempts")
@login_required
def api_attempts():
    match = get_current_match()
    if match is None:
        abort(404)
    team = _team_in_match(match, request.args.get("team_id", type=int))
    challenge_id = request.args.get("challenge_id", type=int)
    attempts = (DrawingAttempt.query
                .filter_by(match_id=match.id, team_id=team.id, challenge_id=challenge_id)
                .order_by(DrawingAttempt.id).all())
    return jsonify({"attempts": [_attempt_dict(a) for a in attempts]})


@drawing_bp.route("/api/attempt", methods=["POST"])
@login_required
def api_attempt():
    match = get_current_match()
    if match is None:
        return _api_error(t("matches.select_first"), 409)
    ensure_open(match, "drawing")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _api_error(t("errors.api_server_error"), 400)
    cfg = _cfg()

    team = _team_in_match(match, body.get("team_id"))
    challenge = DrawingChallenge.query.filter_by(id=body.get("challenge_id"), active=True).first()
    if challenge is None:
        abort(404)
    prompt = str(body.get("prompt", "")).strip()
    language = body.get("language")
    if language not in ("it", "en"):
        language = "it"
    if not prompt:
        return _api_error(t("drawing.empty_prompt"), 400)
    if len(prompt) > cfg.max_prompt_chars:
        return _api_error(t("drawing.prompt_too_long", n=cfg.max_prompt_chars), 400)

    hits = find_forbidden(prompt, challenge.forbidden_list)
    if hits:
        return _api_error(t("drawing.forbidden_rejected", words=", ".join(hits)), 400, forbidden=hits)

    used = DrawingAttempt.query.filter_by(match_id=match.id, team_id=team.id, challenge_id=challenge.id).count()
    if used >= cfg.attempts_per_team:
        return _api_error(t("drawing.no_attempts_left"), 409)

    elements = challenge.elements
    started = time.perf_counter()
    try:
        response = current_app.models.post(WORKER, "/generate", json={
            "prompt": prompt,
            "language": language,
            "queries": [el["query"] for el in elements],
            "threshold": cfg.detection_threshold,
        })
    except WorkerUnavailable:
        return _api_error(t("model.not_ready"), 503)
    except requests.HTTPError as err:
        current_app.logger.error("image_gen worker error: %s", err)
        return _api_error(t("drawing.worker_error"), 502)
    elapsed = round(time.perf_counter() - started, 1)
    result = response.json()

    image_path = new_media_path(match.id, "drawing", "png")
    with open(image_path, "wb") as f:
        f.write(base64.b64decode(result["image_png_base64"]))

    detections = {str(i): det for i, det in enumerate(result["detections"])}
    attempt = DrawingAttempt(
        match_id=match.id, team_id=team.id, challenge_id=challenge.id,
        prompt_text=prompt, translated_text=result["translated"],
        image_path=image_path, detections_json=json.dumps(detections),
    )
    db.session.add(attempt)
    db.session.commit()
    current_app.logger.info("drawing attempt %s: %ss total, worker timings %s", attempt.id, elapsed, result["timings"])
    return jsonify({"attempt": _attempt_dict(attempt), "elapsed": elapsed, "timings": result["timings"],
                    "attempts_left": cfg.attempts_per_team - used - 1})


@drawing_bp.route("/api/attempt/<int:attempt_id>/confirm", methods=["POST"])
@login_required
def api_confirm(attempt_id):
    match = get_current_match()
    if match is None:
        return _api_error(t("matches.select_first"), 409)
    ensure_open(match, "drawing")
    attempt = DrawingAttempt.query.filter_by(id=attempt_id, match_id=match.id).first()
    if attempt is None:
        abort(404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("elements"), list):
        return _api_error(t("errors.api_server_error"), 400)
    n_elements = len(attempt.challenge.elements)
    confirmed = sorted({int(i) for i in body["elements"] if isinstance(i, int) and 0 <= i < n_elements})

    # Only one confirmed attempt per team and scene: the score follows it.
    (DrawingAttempt.query
     .filter(DrawingAttempt.match_id == match.id, DrawingAttempt.team_id == attempt.team_id,
             DrawingAttempt.challenge_id == attempt.challenge_id, DrawingAttempt.id != attempt.id)
     .update({"confirmed_json": None}))
    attempt.confirmed_json = json.dumps(confirmed)
    db.session.commit()

    points = len(confirmed) * _cfg().points_per_element
    found_labels = [attempt.challenge.elements[i][get_locale()] for i in confirmed]
    title = getattr(attempt.challenge, f"title_{get_locale()}")
    add_score(match, attempt.team, "drawing", points, current_user,
              ref=f"drawing:challenge:{attempt.challenge_id}",
              detail={"summary": f"{title}: {', '.join(found_labels) or '-'}", "attempt_id": attempt.id,
                      "elements": confirmed})
    return jsonify({"attempt": _attempt_dict(attempt), "points": points})


@drawing_bp.route("/image/<int:attempt_id>")
@login_required
def image(attempt_id):
    match = get_current_match()
    if match is None:
        abort(404)
    attempt = DrawingAttempt.query.filter_by(id=attempt_id, match_id=match.id).first()
    if attempt is None or attempt.image_path is None or not is_inside_media_dir(attempt.image_path):
        abort(404)
    return send_file(attempt.image_path, mimetype="image/png", max_age=0)


# ------------------------------------------------------------------- content

def _parse_elements(text):
    """Lines 'italiano | english | detector query' (query optional)."""
    elements = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1] or len(parts) > 3:
            raise ValueError(line)
        query = parts[2] if len(parts) == 3 and parts[2] else f"a photo of a {parts[1]}"
        elements.append({"it": parts[0], "en": parts[1], "query": query})
    return elements


def _elements_text(challenge):
    return "\n".join(f"{el['it']} | {el['en']} | {el['query']}" for el in challenge.elements)


def _save_challenge(challenge, form):
    fields = {name: form.get(name, "").strip() for name in ("title_it", "title_en", "brief_it", "brief_en")}
    if not fields["title_it"] or not fields["title_en"]:
        flash(t("drawing.content_title_required"), "error")
        return False
    try:
        elements = _parse_elements(form.get("elements", ""))
    except ValueError as err:
        flash(t("drawing.content_bad_element", line=str(err)), "error")
        return False
    if not elements:
        flash(t("drawing.content_need_elements"), "error")
        return False
    for name, value in fields.items():
        setattr(challenge, name, value[:120] if name.startswith("title") else value)
    challenge.elements_json = json.dumps(elements, ensure_ascii=False)
    challenge.forbidden_words = "\n".join(w.strip() for w in form.get("forbidden_words", "").splitlines() if w.strip())
    return True


@drawing_bp.route("/content")
@login_required
@admin_required
def content():
    challenges = DrawingChallenge.query.order_by(DrawingChallenge.active.desc(), DrawingChallenge.id).all()
    edit_id = request.args.get("edit", type=int)
    editing = db.session.get(DrawingChallenge, edit_id) if edit_id else None
    return render_template("games/drawing_content.html", challenges=challenges, editing=editing,
                           editing_elements=_elements_text(editing) if editing else "")


@drawing_bp.route("/content/new", methods=["POST"])
@login_required
@admin_required
def content_new():
    challenge = DrawingChallenge()
    if _save_challenge(challenge, request.form):
        db.session.add(challenge)
        db.session.commit()
        flash(t("common.saved"), "success")
    return redirect(url_for("drawing.content"))


@drawing_bp.route("/content/<int:challenge_id>/edit", methods=["POST"])
@login_required
@admin_required
def content_edit(challenge_id):
    challenge = DrawingChallenge.query.filter_by(id=challenge_id).first_or_404()
    if _save_challenge(challenge, request.form):
        db.session.commit()
        flash(t("common.saved"), "success")
        return redirect(url_for("drawing.content"))
    db.session.rollback()
    return redirect(url_for("drawing.content", edit=challenge.id))


@drawing_bp.route("/content/<int:challenge_id>/toggle", methods=["POST"])
@login_required
@admin_required
def content_toggle(challenge_id):
    challenge = DrawingChallenge.query.filter_by(id=challenge_id).first_or_404()
    challenge.active = not challenge.active
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("drawing.content"))
