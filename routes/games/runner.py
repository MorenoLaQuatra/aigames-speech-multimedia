"""Game 4 - "Comanda con la voce" (runner).

Each team picks three command words (left / right / jump), records a few
push-to-talk examples of each plus the room noise, and a small classifier is trained on top of
the TensorFlow.js speech-commands model - entirely in the browser
(static/js/runner/). The trained model then steers a 3-lane runner game.

The server only does two things: render the page, and record finished runs.
Runs are scored here from the raw outcome (coins, seconds, hits) - the score
the browser computed is never trusted. Each team plays two scored runs
("trainer": the person who trained the model, "other": someone else); only
the best run per phase counts, so replaying cannot farm points.
"""

import math

from flask import Blueprint, current_app, jsonify, render_template, request, url_for
from flask_login import current_user, login_required

from i18n import t
from models import ScoreEvent, Team
from services.context import admin_required, get_current_match, require_current_match
from services.scoring import add_score

runner_bp = Blueprint("runner", __name__, url_prefix="/games/runner")

PHASES = ("trainer", "other")
COMMANDS = ("left", "right", "jump")


def _cfg():
    return current_app.games_config.games.runner


def _settings():
    cfg = _cfg()
    return {
        "turnSeconds": cfg.turn_seconds,
        "examplesPerCommand": cfg.examples_per_command,
        "backgroundSeconds": cfg.background_seconds,
        "maxExampleSeconds": cfg.max_example_seconds,
        "augmentNoiseRatio": cfg.augment_noise_ratio,
        "trainingEpochs": cfg.training_epochs,
        "runSeconds": cfg.run_seconds,
        "lives": cfg.lives,
        "pointsPerCoin": cfg.points_per_coin,
        "pointsPerSecond": cfg.points_per_second,
        "probabilityThreshold": cfg.probability_threshold,
        "suppressionMs": cfg.suppression_ms,
        "overlapFactor": cfg.overlap_factor,
        "fallSeconds": cfg.fall_seconds,
        "spawnIntervalSeconds": cfg.spawn_interval_seconds,
        "jumpSeconds": cfg.jump_seconds,
    }


def _strings():
    keys = [
        "cmd_left", "cmd_right", "cmd_jump", "cmd_background",
        "say_word", "stay_silent", "examples_count", "background_done", "background_todo", "redo",
        "hold_to_talk", "release_to_save", "recording_word", "saving_example", "remove_example",
        "train", "training", "epoch_progress", "trained", "train_first", "need_examples",
        "loading_model", "model_load_failed", "mic_failed",
        "test_on", "test_off", "listening", "last_command", "nothing_yet", "noise_label",
        "run_trainer", "run_other", "run_practice", "get_ready", "goal_hint", "go", "run_over_time", "run_over_lives",
        "practice_over", "saving", "saved_points", "kept_previous", "save_failed",
        "hud_time", "hud_lives", "hud_coins", "hud_score",
        "confirm_team_change", "compare_better", "compare_worse", "compare_same", "compare_missing",
        "col_coins", "col_seconds", "col_hits", "col_points", "phase_trainer", "phase_other",
    ]
    return {key: t(f"runner.{key}") for key in keys}


def _run_points(coins, seconds):
    cfg = _cfg()
    return coins * cfg.points_per_coin + int(math.floor(seconds)) * cfg.points_per_second


@runner_bp.route("/")
@login_required
@require_current_match
def play(match):
    vendor = "vendor/speech-commands-0.5.4/model-18w/"
    page_config = {
        "settings": _settings(),
        "strings": _strings(),
        "urls": {
            "run": url_for("runner.api_run"),
            "modelJson": url_for("static", filename=vendor + "model.json"),
            "metadataJson": url_for("static", filename=vendor + "metadata.json"),
        },
    }
    return render_template("games/runner.html", match=match, cfg=_cfg(), page_config=page_config)


def _bad(message):
    return jsonify({"error": message}), 400


def _int_field(body, name, low, high):
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise ValueError(name)
    value = int(value)
    if not low <= value <= high:
        raise ValueError(name)
    return value


@runner_bp.route("/api/run", methods=["POST"])
@login_required
def api_run():
    match = get_current_match()
    if match is None:
        return jsonify({"error": t("matches.select_first")}), 409
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _bad(t("runner.invalid_run"))

    cfg = _cfg()
    phase = body.get("phase")
    if phase not in PHASES:
        return _bad(t("runner.invalid_run"))
    max_seconds = cfg.run_seconds + cfg.seconds_slack
    # At most one coin per spawn slot (plus one for rounding at the edges).
    max_coins = int(max_seconds / cfg.spawn_interval_seconds) + 1
    try:
        team_id = _int_field(body, "team_id", 1, 2**31)
        coins = _int_field(body, "coins", 0, max_coins)
        hits = _int_field(body, "hits", 0, cfg.lives)
        seconds = _int_field(body, "seconds", 0, max_seconds)
    except ValueError:
        return _bad(t("runner.invalid_run"))
    if hits < cfg.lives and seconds < cfg.run_seconds - cfg.seconds_slack:
        # A run only ends early when all lives are lost.
        return _bad(t("runner.invalid_run"))
    seconds = min(seconds, cfg.run_seconds)

    team = Team.query.filter_by(id=team_id, match_id=match.id).first()
    if team is None:
        return _bad(t("runner.invalid_run"))

    points = _run_points(coins, seconds)
    ref = f"runner:{phase}"
    previous = ScoreEvent.query.filter_by(match_id=match.id, team_id=team.id, ref=ref).first()
    kept_previous = previous is not None and previous.points >= points
    if not kept_previous:
        summary = t("runner.summary", phase=t(f"runner.phase_{phase}"), coins=coins, seconds=seconds, hits=hits)
        add_score(match, team, "runner", points, current_user, ref=ref,
                  detail={"summary": summary, "phase": phase, "coins": coins, "seconds": seconds, "hits": hits,
                          "trained_sounds": _sound_names(body)})
    return jsonify({
        "points": points,
        "kept_previous": kept_previous,
        "best": previous.points if kept_previous else points,
    })


def _sound_names(body):
    """The team's own names for their sounds (free text, display only)."""
    names = body.get("sounds")
    if not isinstance(names, dict):
        return {}
    return {cmd: str(names[cmd])[:40] for cmd in COMMANDS if cmd in names}


@runner_bp.route("/content")
@login_required
@admin_required
def content():
    # Config is dict-like: list every games.runner key in file order.
    return render_template("games/runner_content.html", settings=dict(_cfg().items()))
