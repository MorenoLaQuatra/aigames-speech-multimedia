"""Shared plumbing for model worker processes (workers/*.py).

A worker is a tiny local HTTP server around one model family. It is never
started by hand: services/model_manager.py launches it with two environment
variables, AI_GAMES_WORKER (its name under models.workers) and
AI_GAMES_CONFIG_PATH, loads the model, and only then starts serving - so
GET /health answering 200 means "model loaded and ready".

Workers serve one request at a time (threaded=False): the models are not
thread-safe, and a game only ever needs one inference at a time.
"""

import logging
import os
import sys

from flask import Flask, jsonify
from yaml_config_manager import load_config

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


def load_worker_config():
    """Returns (full_config, this_worker_config, worker_name)."""
    name = os.environ["AI_GAMES_WORKER"]
    config = load_config(config_path=os.environ["AI_GAMES_CONFIG_PATH"], args=[])
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s %(levelname)s [{name}] %(message)s")
    return config, config.models.workers[name], name


def resolve_device(device):
    """'cuda' falls back to failing loudly if CUDA isn't there - no silent CPU fallback."""
    import torch

    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(f"Configured device {device!r} but CUDA is not available")
    return torch.device(device)


def create_worker_app(name):
    app = Flask(name)

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "worker": name})

    return app


def json_error(message, status):
    return jsonify({"error": message}), status


def serve(app, worker_cfg):
    logging.getLogger(__name__).info("Serving on %s:%s", worker_cfg.host, worker_cfg.port)
    app.run(host=worker_cfg.host, port=worker_cfg.port, threaded=False, debug=False, use_reloader=False)
