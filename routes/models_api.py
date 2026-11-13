"""JSON endpoints for the model processes: status polling (game pages show a
"model ready" badge) and start/stop (game pages start their model on open;
the admin panel can stop any of them to free the GPU)."""

from flask import Blueprint, abort, current_app, jsonify
from flask_login import login_required

from services.context import admin_required

models_bp = Blueprint("models_api", __name__, url_prefix="/models")


def _check_name(name):
    if name not in current_app.models.workers:
        abort(404)


@models_bp.route("/api/status")
@login_required
def all_status():
    return jsonify({"workers": current_app.models.all_status()})


@models_bp.route("/api/<name>/status")
@login_required
def status(name):
    _check_name(name)
    return jsonify(current_app.models.status(name))


@models_bp.route("/api/<name>/start", methods=["POST"])
@login_required
def start(name):
    _check_name(name)
    current_app.models.ensure_started(name)
    return jsonify(current_app.models.status(name))


@models_bp.route("/api/<name>/stop", methods=["POST"])
@login_required
@admin_required
def stop(name):
    _check_name(name)
    current_app.models.stop(name)
    return jsonify(current_app.models.status(name))


@models_bp.route("/api/stop-all", methods=["POST"])
@login_required
@admin_required
def stop_all():
    current_app.models.stop_all()
    return jsonify({"workers": current_app.models.all_status()})
