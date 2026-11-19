"""Game 1 - "Sound Challenge": a team imitates a sound with their voice, an
AudioSet classifier (workers/audio_classifier.py) listens, and the team
scores if the target sound is among its top predictions.

Sounds are grouped in categories (animals / human sounds / other) of similar
difficulty: the team picks a category and gets a random sound from it.

Scoring (config.games.noise.points_by_rank): the best rank of any of the
target's AudioSet labels decides the points. A team scores each target at
most once - a better retry replaces the earlier score (ScoreEvent ref
"noise:target:<id>"), a worse one adds nothing. Misses are logged as
0-point events so the match log shows every attempt.
"""

import random

import requests
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from content.audioset_it import AUDIOSET_IT
from content.noise import AUDIOSET_LABELS, unknown_labels
from extensions import db
from i18n import get_locale, localized, t
from models import NOISE_CATEGORIES, NoiseTarget, ScoreEvent, Team
from services.context import admin_required, get_current_match, require_current_match
from services.model_manager import WorkerUnavailable
from services.scoring import add_score

noise_bp = Blueprint("noise", __name__, url_prefix="/games/noise")

WORKER = "audio_classifier"


def _target_dict(target):
    return {
        "id": target.id,
        "name": localized(target, "name"),
        "emoji": target.emoji,
        "category": target.category,
        "labels": target.label_list,
    }


# ------------------------------------------------------------------- play

@noise_bp.route("/")
@login_required
@require_current_match
def play(match):
    cfg = current_app.games_config.games.noise
    page_config = {
        "nextUrl": url_for("noise.api_next"),
        "attemptUrl": url_for("noise.api_attempt"),
        "categories": {category: t(f"noise.category_{category}") for category in NOISE_CATEGORIES},
        "recordSeconds": cfg.record_seconds,
        "countdownSeconds": cfg.countdown_seconds,
        "topK": cfg.top_k_shown,
        "strings": {
            "getReady": t("noise.get_ready"),
            "recording": t("noise.recording"),
            "thinking": t("noise.thinking"),
            "hit": t("noise.hit"),
            "miss": t("noise.miss"),
            "alreadyScored": t("noise.already_scored"),
            "micError": t("noise.mic_error"),
            "modelNotReady": t("model.not_ready"),
            "tooQuiet": t("noise.too_quiet"),
        },
    }
    return render_template("games/noise.html", match=match, page_config=page_config,
                           turn_seconds=cfg.turn_seconds, points_by_rank=cfg.points_by_rank)


def _team_in_match(match, team_id):
    team = Team.query.filter_by(id=team_id, match_id=match.id).first()
    if team is None:
        abort(400)
    return team


def _used_target_ids(match, team):
    events = ScoreEvent.query.filter_by(match_id=match.id, team_id=team.id, game="noise").all()
    return {event.detail["target_id"] for event in events if "target_id" in event.detail}


@noise_bp.route("/api/next")
@login_required
def api_next():
    """A random active target of the chosen category that this team hasn't
    tried yet in this match (falls back to any of that category once they
    have tried them all)."""
    match = get_current_match()
    if match is None:
        abort(404)
    team = _team_in_match(match, request.args.get("team_id", type=int))
    category = request.args.get("category", "")
    if category not in NOISE_CATEGORIES:
        abort(400)
    current_id = request.args.get("current_id", type=int)
    targets = NoiseTarget.query.filter_by(active=True, category=category).all()
    if not targets:
        return jsonify({"error": t("noise.no_targets_category")}), 409
    used = _used_target_ids(match, team)
    fresh = [tg for tg in targets if tg.id not in used and tg.id != current_id]
    pool = fresh or [tg for tg in targets if tg.id != current_id] or targets
    return jsonify(_target_dict(random.choice(pool)))


def _label_name(label):
    """AudioSet label as shown to the class: Italian when the UI is Italian."""
    return AUDIOSET_IT.get(label, label) if get_locale() == "it" else label


def _best_rank(predictions, labels, max_rank):
    """1-based rank of the first prediction that is one of `labels`, within max_rank; else None."""
    wanted = set(labels)
    for index, prediction in enumerate(predictions[:max_rank]):
        if prediction["label"] in wanted:
            return index + 1
    return None


@noise_bp.route("/api/attempt", methods=["POST"])
@login_required
def api_attempt():
    match = get_current_match()
    if match is None:
        abort(404)
    team = _team_in_match(match, request.form.get("team_id", type=int))
    target = db.session.get(NoiseTarget, request.form.get("target_id", type=int))
    if target is None:
        abort(400)
    audio = request.files.get("audio")
    if audio is None:
        return jsonify({"error": t("noise.no_audio")}), 400

    try:
        response = current_app.models.post(WORKER, "/classify",
                                           files={"audio": ("rec.wav", audio.read(), "audio/wav")})
    except WorkerUnavailable:
        return jsonify({"error": t("model.not_ready")}), 503
    except requests.HTTPError as exc:
        # Worker 4xx = bad recording (too short, unreadable): the client's fault, not a gateway error.
        status = 400 if exc.response.status_code < 500 else 502
        return jsonify({"error": str(exc)}), status
    result = response.json()
    predictions = result["predictions"]
    for prediction in predictions:
        prediction["name"] = _label_name(prediction["label"])

    points_by_rank = current_app.games_config.games.noise.points_by_rank
    rank = _best_rank(predictions, target.label_list, len(points_by_rank))
    points = points_by_rank[rank - 1] if rank else 0
    name = localized(target, "name")
    top_label = predictions[0]["name"]
    detail = {"target_id": target.id, "target": target.name_en, "rank": rank,
              "top": [p["label"] for p in predictions[:5]]}

    ref = f"noise:target:{target.id}"
    previous = ScoreEvent.query.filter_by(match_id=match.id, team_id=team.id, ref=ref).first()
    already_scored = bool(rank) and previous is not None and previous.points >= points
    if rank and not already_scored:
        detail["summary"] = t("noise.log_hit", name=name, rank=rank)
        add_score(match, team, "noise", points, current_user, detail=detail, ref=ref)
        awarded = points
    else:
        detail["summary"] = (t("noise.log_already", name=name, rank=rank) if already_scored
                             else t("noise.log_miss", name=name, heard=top_label))
        add_score(match, team, "noise", 0, current_user, detail=detail)
        awarded = 0

    return jsonify({
        "rank": rank,
        "points": awarded,
        "alreadyScored": already_scored,
        "targetLabels": target.label_list,
        "predictions": predictions,
        "rms": result["rms"],
    })


# ---------------------------------------------------------------- content

def _form_values():
    labels = [line.strip() for line in request.form.get("labels", "").splitlines() if line.strip()]
    return {
        "name_it": request.form.get("name_it", "").strip()[:80],
        "name_en": request.form.get("name_en", "").strip()[:80],
        "emoji": request.form.get("emoji", "").strip()[:16],
        "category": request.form.get("category", ""),
        "labels": labels,
    }


def _validate(values):
    """Returns an error message or None."""
    if not values["name_it"] or not values["name_en"] or not values["labels"]:
        return t("noise.content_required")
    if values["category"] not in NOISE_CATEGORIES:
        return t("noise.content_required")
    bad = unknown_labels(values["labels"])
    if bad:
        return t("noise.content_unknown_labels", labels=", ".join(bad))
    return None


def _content_page(form_target=None, form_values=None):
    targets = NoiseTarget.query.order_by(NoiseTarget.active.desc(), NoiseTarget.name_it.asc()).all()
    by_category = {category: [tg for tg in targets if tg.category == category] for category in NOISE_CATEGORIES}
    return render_template("games/noise_content.html", targets=targets, by_category=by_category,
                           categories=NOISE_CATEGORIES, form_target=form_target,
                           form_values=form_values, audioset_labels=AUDIOSET_LABELS)


@noise_bp.route("/content")
@login_required
@admin_required
def content():
    edit_id = request.args.get("edit", type=int)
    form_target = db.session.get(NoiseTarget, edit_id) if edit_id else None
    return _content_page(form_target=form_target)


@noise_bp.route("/content/save", methods=["POST"])
@login_required
@admin_required
def content_save():
    target_id = request.form.get("target_id", type=int)
    target = db.session.get(NoiseTarget, target_id) if target_id else None
    if target_id and target is None:
        abort(404)
    values = _form_values()
    error = _validate(values)
    if error:
        flash(error, "error")
        return _content_page(form_target=target, form_values={**values, "labels": "\n".join(values["labels"])})
    if target is None:
        target = NoiseTarget()
        db.session.add(target)
    target.name_it = values["name_it"]
    target.name_en = values["name_en"]
    target.emoji = values["emoji"]
    target.category = values["category"]
    target.labels = "\n".join(values["labels"])
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("noise.content"))


@noise_bp.route("/content/<int:target_id>/toggle", methods=["POST"])
@login_required
@admin_required
def content_toggle(target_id):
    target = db.session.get(NoiseTarget, target_id)
    if target is None:
        abort(404)
    target.active = not target.active
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("noise.content"))

