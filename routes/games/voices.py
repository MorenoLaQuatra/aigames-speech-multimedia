"""Game 2 - "Di chi è la voce?" (voice cloning guessing game).

All teams play at the same time:
  1. Setup: each team sends one or more volunteers; each records ~12 s
     reading a text aloud (the voice reference).
  2. Generate: the app clones every volunteer's voice saying a few random
     phrases (services/voice_jobs.py, in the background), in shuffled rounds.
  3. Play: each round plays one cloned clip; every team picks whose voice it
     is; "Reveal" shows the answer and awards points to the right guesses.

Recordings and clips are personal data: they live under the match's media
folder, are only served to logged-in users for the current match, and are
deleted when the match is archived (or with "delete recordings now").
"""

import io
import os
import random
from datetime import datetime, timezone

import soundfile as sf
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import SelectField, TextAreaField
from wtforms.validators import DataRequired, Length

from extensions import db
from i18n import t
from models import (CLIP_FAILED, CLIP_PENDING, CLIP_READY, Team, VoiceClip, VoiceGuess, VoicePhrase,
                    VoiceVolunteer)
from services import voice_jobs
from services.context import admin_required, require_current_match
from services.media import is_inside_media_dir, new_media_path
from services.scoring import add_score

voices_bp = Blueprint("voices", __name__, url_prefix="/games/voices")

MAX_NICKNAME = 60
MIN_REFERENCE_SECONDS = 3
LANGUAGES = ("it", "en")


# ------------------------------------------------------------------ helpers

def _cfg():
    return current_app.games_config.games.voices


def _volunteer_or_404(match, volunteer_id):
    volunteer = VoiceVolunteer.query.filter_by(id=volunteer_id, match_id=match.id).first()
    if volunteer is None:
        abort(404)
    return volunteer


def _clip_or_404(match, clip_id):
    clip = VoiceClip.query.filter_by(id=clip_id, match_id=match.id).first()
    if clip is None:
        abort(404)
    return clip


def _send_media(path):
    if path is None or not is_inside_media_dir(path) or not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="audio/wav", conditional=True, max_age=0)


def _remove_file(path):
    if path and is_inside_media_dir(path) and os.path.isfile(path):
        os.remove(path)


def _volunteer_json(volunteer, has_clips):
    return {
        "id": volunteer.id,
        "nickname": volunteer.nickname,
        "teamId": volunteer.team_id,
        "hasClips": has_clips,
        "consent": volunteer.consent_confirmed_at is not None,
        "hasReference": volunteer.reference_path is not None,
        "referenceUrl": url_for("voices.reference_audio", volunteer_id=volunteer.id) if volunteer.reference_path else None,
    }


def _clip_json(clip, guesses):
    """The answer (volunteer) is only included once the clip is revealed, so
    it never sits in the page before the reveal."""
    data = {
        "id": clip.id,
        "round": clip.round_number,
        "status": clip.status,
        "error": clip.error,
        "revealed": clip.revealed,
        "audioUrl": url_for("voices.clip_audio", clip_id=clip.id) if clip.status == CLIP_READY else None,
        "guesses": {str(g.team_id): g.guessed_volunteer_id for g in guesses},
    }
    if clip.revealed:
        data["volunteerId"] = clip.volunteer_id
        data["phrase"] = clip.phrase_text
    return data


def _state(match):
    volunteers = VoiceVolunteer.query.filter_by(match_id=match.id).order_by(VoiceVolunteer.id).all()
    clips = VoiceClip.query.filter_by(match_id=match.id).order_by(VoiceClip.round_number).all()
    guesses_by_clip = {}
    if clips:
        for guess in VoiceGuess.query.filter(VoiceGuess.clip_id.in_([c.id for c in clips])):
            guesses_by_clip.setdefault(guess.clip_id, []).append(guess)
    return {
        "volunteers": [_volunteer_json(v, v.id in {c.volunteer_id for c in clips}) for v in volunteers],
        "clips": [_clip_json(c, guesses_by_clip.get(c.id, [])) for c in clips],
        "jobRunning": voice_jobs.is_running(match.id),
        "counts": {
            "total": len(clips),
            "ready": sum(c.status == CLIP_READY for c in clips),
            "pending": sum(c.status == CLIP_PENDING for c in clips),
            "failed": sum(c.status == CLIP_FAILED for c in clips),
        },
    }


def _round_order(volunteers, per_volunteer):
    """Each volunteer `per_volunteer` times, shuffled, never the same
    volunteer twice in a row when that is avoidable (greedy: always draw from
    the volunteers with the most clips left, excluding the previous one)."""
    remaining = {v.id: per_volunteer for v in volunteers}
    order, previous = [], None
    while any(remaining.values()):
        candidates = [vid for vid, n in remaining.items() if n > 0 and vid != previous]
        if not candidates:  # only the previous volunteer is left
            candidates = [previous]
        most = max(remaining[vid] for vid in candidates)
        choice = random.choice([vid for vid in candidates if remaining[vid] == most])
        order.append(choice)
        remaining[choice] -= 1
        previous = choice
    return order


def _pick_phrases(match, count, language):
    """`count` phrases, avoiding phrases already used in this match; repeats
    only if the active phrase list is shorter than what's needed."""
    used = {c.phrase_text for c in VoiceClip.query.filter_by(match_id=match.id)}
    pool = [p.text for p in VoicePhrase.query.filter_by(active=True, language=language)]
    if not pool:
        return None
    fresh = [p for p in pool if p not in used]
    random.shuffle(fresh)
    picked = fresh[:count]
    while len(picked) < count:
        extra = pool[:]
        random.shuffle(extra)
        picked.extend(extra[: count - len(picked)])
    return picked


def _json_error(key, status=400, **kwargs):
    return jsonify({"error": t(key, **kwargs)}), status


# --------------------------------------------------------------------- page

@voices_bp.route("/")
@login_required
@require_current_match
def play(match):
    cfg = _cfg()
    page_config = {
        "urls": {
            "state": url_for("voices.api_state"),
            "addVolunteer": url_for("voices.api_add_volunteer"),
            "volunteer": url_for("voices.api_volunteer", volunteer_id=0),
            "reference": url_for("voices.api_upload_reference", volunteer_id=0),
            "consent": url_for("voices.api_consent", volunteer_id=0),
            "generate": url_for("voices.api_generate"),
            "retry": url_for("voices.api_retry"),
            "guess": url_for("voices.api_guess", clip_id=0),
            "reveal": url_for("voices.api_reveal", clip_id=0),
            "deleteRecordings": url_for("voices.api_delete_recordings"),
        },
        "referenceSeconds": cfg.reference_seconds,
        "minReferenceSeconds": MIN_REFERENCE_SECONDS,
        "teams": [{"id": team.id, "name": team.name, "color": team.color} for team in match.teams],
        "ownTeamCanScore": cfg.own_team_can_score,
        "requireConsent": cfg.require_consent,
        "pointsCorrect": cfg.points_correct,
        "strings": {key.split(".", 1)[1]: t(key) for key in _JS_STRING_KEYS},
    }
    return render_template("games/voices.html", match=match, cfg=cfg, page_config=page_config,
                           reading_text=t(f"voices.reading_text_{cfg.language}"))


_JS_STRING_KEYS = (
    "voices.js_record", "voices.js_rerecord", "voices.js_recording", "voices.js_stop", "voices.js_saved",
    "voices.js_too_short", "voices.js_no_reference", "voices.js_has_reference", "voices.js_delete",
    "voices.js_confirm_delete_volunteer", "voices.js_round", "voices.js_rounds_progress", "voices.js_pending",
    "voices.js_generating", "voices.js_failed", "voices.js_ready", "voices.js_play_clip", "voices.js_choose",
    "voices.js_reveal", "voices.js_reveal_again", "voices.js_next", "voices.js_prev", "voices.js_it_was",
    "voices.js_correct", "voices.js_wrong", "voices.js_own_team", "voices.js_points", "voices.js_play_original",
    "voices.js_no_clips", "voices.js_waiting_clip", "voices.js_mic_error", "voices.js_confirm_delete_recordings",
    "voices.js_no_guess", "voices.js_all_done", "voices.js_phrase", "voices.js_nickname_required",
    "voices.js_reference_of", "voices.js_volunteers_of", "voices.nickname_placeholder",
    "voices.consent_label", "voices.js_consent_badge", "voices.err_consent_required",
)


# ----------------------------------------------------------------- JSON API

@voices_bp.route("/api/state")
@login_required
@require_current_match
def api_state(match):
    return jsonify(_state(match))


@voices_bp.route("/api/volunteers", methods=["POST"])
@login_required
@require_current_match
def api_add_volunteer(match):
    payload = request.get_json(silent=False)
    nickname = str(payload["nickname"]).strip()[:MAX_NICKNAME]
    team = Team.query.filter_by(id=int(payload["teamId"]), match_id=match.id).first()
    if team is None:
        abort(404)
    if not nickname:
        return _json_error("voices.js_nickname_required")
    db.session.add(VoiceVolunteer(match_id=match.id, team_id=team.id, nickname=nickname))
    db.session.commit()
    return jsonify(_state(match))


@voices_bp.route("/api/volunteers/<int:volunteer_id>", methods=["DELETE"])
@login_required
@require_current_match
def api_volunteer(match, volunteer_id):
    volunteer = _volunteer_or_404(match, volunteer_id)
    if VoiceClip.query.filter_by(volunteer_id=volunteer.id).first() is not None:
        return _json_error("voices.err_volunteer_has_clips", 409)
    _remove_file(volunteer.reference_path)
    db.session.delete(volunteer)
    db.session.commit()
    return jsonify(_state(match))


@voices_bp.route("/api/volunteers/<int:volunteer_id>/consent", methods=["POST"])
@login_required
@require_current_match
def api_consent(match, volunteer_id):
    """Record that the instructor confirmed consent for this volunteer
    (only meaningful when games.voices.require_consent is true)."""
    volunteer = _volunteer_or_404(match, volunteer_id)
    if volunteer.consent_confirmed_at is None:
        volunteer.consent_confirmed_at = datetime.now(timezone.utc)
        volunteer.consent_confirmed_by_id = current_user.id
        db.session.commit()
    return jsonify(_state(match))


@voices_bp.route("/api/volunteers/<int:volunteer_id>/reference", methods=["POST"])
@login_required
@require_current_match
def api_upload_reference(match, volunteer_id):
    volunteer = _volunteer_or_404(match, volunteer_id)
    if _cfg().require_consent and volunteer.consent_confirmed_at is None:
        return _json_error("voices.err_consent_required")
    upload = request.files.get("audio")
    if upload is None:
        return _json_error("voices.err_no_audio")
    data = upload.read()
    try:
        info = sf.info(io.BytesIO(data))
    except sf.LibsndfileError:
        return _json_error("voices.err_bad_audio")
    if info.duration < MIN_REFERENCE_SECONDS:
        return _json_error("voices.js_too_short", n=MIN_REFERENCE_SECONDS)
    # Re-recording is allowed until the volunteer's clips exist; afterwards
    # the clips would no longer match the reference.
    if VoiceClip.query.filter_by(volunteer_id=volunteer.id).first() is not None:
        return _json_error("voices.err_volunteer_has_clips", 409)
    path = new_media_path(match.id, "voice-ref", "wav")
    with open(path, "wb") as out:
        out.write(data)
    _remove_file(volunteer.reference_path)
    volunteer.reference_path = path
    db.session.commit()
    return jsonify(_state(match))


@voices_bp.route("/api/generate", methods=["POST"])
@login_required
@require_current_match
def api_generate(match):
    """Create clips for every volunteer with a reference and no clips yet,
    appended after any existing rounds, then start the background job."""
    cfg = _cfg()
    volunteers = [v for v in VoiceVolunteer.query.filter_by(match_id=match.id).order_by(VoiceVolunteer.id)
                  if v.reference_path is not None
                  and VoiceClip.query.filter_by(volunteer_id=v.id).first() is None]
    if not volunteers:
        return _json_error("voices.err_nothing_to_generate")
    order = _round_order(volunteers, cfg.clips_per_volunteer)
    phrases = _pick_phrases(match, len(order), cfg.language)
    if phrases is None:
        return _json_error("voices.err_no_phrases")
    last_round = db.session.query(db.func.max(VoiceClip.round_number)).filter_by(match_id=match.id).scalar() or 0
    for offset, (volunteer_id, phrase) in enumerate(zip(order, phrases), start=1):
        db.session.add(VoiceClip(match_id=match.id, volunteer_id=volunteer_id, round_number=last_round + offset,
                                 phrase_text=phrase, language=cfg.language))
    db.session.commit()
    voice_jobs.start(current_app._get_current_object(), match.id)
    return jsonify(_state(match))


@voices_bp.route("/api/retry", methods=["POST"])
@login_required
@require_current_match
def api_retry(match):
    VoiceClip.query.filter_by(match_id=match.id, status=CLIP_FAILED).update(
        {"status": CLIP_PENDING, "error": None})
    db.session.commit()
    if VoiceClip.query.filter_by(match_id=match.id, status=CLIP_PENDING).first() is not None:
        voice_jobs.start(current_app._get_current_object(), match.id)
    return jsonify(_state(match))


@voices_bp.route("/api/clips/<int:clip_id>/guess", methods=["POST"])
@login_required
@require_current_match
def api_guess(match, clip_id):
    """Set (or clear, with volunteerId null) one team's guess for a clip."""
    clip = _clip_or_404(match, clip_id)
    if clip.revealed:
        return _json_error("voices.err_already_revealed", 409)
    payload = request.get_json(silent=False)
    team = Team.query.filter_by(id=int(payload["teamId"]), match_id=match.id).first()
    if team is None:
        abort(404)
    guess = VoiceGuess.query.filter_by(clip_id=clip.id, team_id=team.id).first()
    if payload["volunteerId"] is None:
        if guess is not None:
            db.session.delete(guess)
    else:
        volunteer = _volunteer_or_404(match, int(payload["volunteerId"]))
        if guess is None:
            guess = VoiceGuess(clip_id=clip.id, team_id=team.id, guessed_volunteer_id=volunteer.id)
            db.session.add(guess)
        guess.guessed_volunteer_id = volunteer.id
    db.session.commit()
    return jsonify(_state(match))


@voices_bp.route("/api/clips/<int:clip_id>/reveal", methods=["POST"])
@login_required
@require_current_match
def api_reveal(match, clip_id):
    """Reveal the answer and score every team that guessed. Scores use
    ref="voices:clip:<id>", so revealing twice never double-counts."""
    cfg = _cfg()
    clip = _clip_or_404(match, clip_id)
    if clip.status != CLIP_READY:
        return _json_error("voices.err_clip_not_ready", 409)
    answer = clip.volunteer
    for guess in VoiceGuess.query.filter_by(clip_id=clip.id):
        team = db.session.get(Team, guess.team_id)
        correct = guess.guessed_volunteer_id == answer.id
        own_team = team.id == answer.team_id
        points = cfg.points_correct if correct and (cfg.own_team_can_score or not own_team) else 0
        summary = t("voices.summary", round=clip.round_number, name=answer.nickname,
                    result=t("voices.summary_right") if correct else t("voices.summary_wrong"))
        add_score(match, team, "voices", points, current_user, ref=f"voices:clip:{clip.id}",
                  detail={"summary": summary, "clip_id": clip.id, "correct": correct, "own_team": own_team})
    clip.revealed = True
    db.session.commit()
    return jsonify(_state(match))


@voices_bp.route("/api/recordings", methods=["DELETE"])
@login_required
@require_current_match
def api_delete_recordings(match):
    """Delete every voice recording and cloned clip of this match now (the
    scores stay). Volunteers stay listed but need to record again to play
    new rounds."""
    for volunteer in VoiceVolunteer.query.filter_by(match_id=match.id):
        _remove_file(volunteer.reference_path)
        volunteer.reference_path = None
    for clip in VoiceClip.query.filter_by(match_id=match.id):
        _remove_file(clip.audio_path)
        clip.audio_path = None
        # Revealed rounds keep their scores and revealed flag; every clip is
        # unplayable now, so none may show a play button any more.
        clip.status = CLIP_FAILED
        clip.error = t("voices.err_recordings_deleted")
    db.session.commit()
    return jsonify(_state(match))


# -------------------------------------------------------------- audio files

@voices_bp.route("/audio/reference/<int:volunteer_id>.wav")
@login_required
@require_current_match
def reference_audio(match, volunteer_id):
    return _send_media(_volunteer_or_404(match, volunteer_id).reference_path)


@voices_bp.route("/audio/clip/<int:clip_id>.wav")
@login_required
@require_current_match
def clip_audio(match, clip_id):
    clip = _clip_or_404(match, clip_id)
    if clip.status != CLIP_READY:
        abort(404)
    return _send_media(clip.audio_path)


# ------------------------------------------------------------ admin content

class PhraseForm(FlaskForm):
    text = TextAreaField(validators=[DataRequired(), Length(max=300)])
    language = SelectField(choices=[(code, code) for code in LANGUAGES], validators=[DataRequired()])


@voices_bp.route("/content")
@login_required
@admin_required
def content():
    phrases = VoicePhrase.query.order_by(VoicePhrase.active.desc(), VoicePhrase.language, VoicePhrase.id).all()
    counts = {code: VoicePhrase.query.filter_by(active=True, language=code).count() for code in LANGUAGES}
    return render_template("games/voices_content.html", phrases=phrases, form=PhraseForm(), counts=counts,
                           languages=LANGUAGES, game_language=_cfg().language)


@voices_bp.route("/content/phrases", methods=["POST"])
@login_required
@admin_required
def content_add():
    form = PhraseForm()
    if form.validate_on_submit():
        db.session.add(VoicePhrase(text=form.text.data.strip(), language=form.language.data))
        db.session.commit()
        flash(t("common.saved"), "success")
    else:
        flash(t("voices.content_invalid"), "error")
    return redirect(url_for("voices.content"))


@voices_bp.route("/content/phrases/<int:phrase_id>", methods=["POST"])
@login_required
@admin_required
def content_edit(phrase_id):
    phrase = VoicePhrase.query.filter_by(id=phrase_id).first_or_404()
    form = PhraseForm()
    if form.validate_on_submit():
        phrase.text = form.text.data.strip()
        phrase.language = form.language.data
        db.session.commit()
        flash(t("common.saved"), "success")
    else:
        flash(t("voices.content_invalid"), "error")
    return redirect(url_for("voices.content"))


@voices_bp.route("/content/phrases/<int:phrase_id>/toggle", methods=["POST"])
@login_required
@admin_required
def content_toggle(phrase_id):
    phrase = VoicePhrase.query.filter_by(id=phrase_id).first_or_404()
    phrase.active = not phrase.active
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("voices.content"))
