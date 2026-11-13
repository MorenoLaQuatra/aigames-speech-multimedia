"""AI Games: app factory, CLI commands, dev server.

The only thing to launch is the webapp (./start.sh, or `python app.py` for
development). Model processes are started and stopped by the webapp itself
(services/model_manager.py).

    python app.py                                    # dev server (accepts --dotted.config overrides)
    ./start.sh                                       # production (gunicorn), see README.md
    flask --app "app:build" create-admin             # bootstrap the first admin
    flask --app "app:build" seed-content             # load the default game content

build() passes args=[] to load_config: under flask/gunicorn, sys.argv
belongs to those tools, not to us.
"""

import atexit
import logging
import os
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

import click  # noqa: E402
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for  # noqa: E402
from flask_login import current_user  # noqa: E402
from yaml_config_manager import load_config  # noqa: E402

from extensions import csrf, db, login_manager  # noqa: E402
from i18n import get_locale, localized, t  # noqa: E402
from services.scoring import GameFinishedError, clean_points, finished_games  # noqa: E402
from models import ROLE_ADMIN, User  # noqa: E402
from routes.games import GAMES  # noqa: E402
from services.context import get_current_match  # noqa: E402
from services.model_manager import ModelManager  # noqa: E402

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(APP_ROOT, "configs", "app.yaml")


def create_app(config, config_path):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.games_config = config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app.config["SECRET_KEY"] = _require_env("SECRET_KEY")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(APP_ROOT, config.database.path)}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=config.app.session_lifetime_hours)
    # CSRF tokens live as long as the login session. Flask-WTF's default (1 h)
    # broke game pages left open longer: every POST from them (e.g. starting a
    # model) failed with "The CSRF token has expired".
    app.config["WTF_CSRF_TIME_LIMIT"] = config.app.session_lifetime_hours * 3600
    app.config["MAX_CONTENT_LENGTH"] = config.app.max_upload_mb * 1024 * 1024
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    os.makedirs(os.path.dirname(os.path.join(APP_ROOT, config.database.path)), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        db.create_all()

    app.models = ModelManager(config, APP_ROOT, config_path)
    atexit.register(app.models.stop_all)

    _register_blueprints(app)
    _register_cli_commands(app)
    _register_error_handlers(app)
    _register_template_globals(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    return app


def _require_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing environment variable {name!r}. Copy .env.example to .env and set it.")
    return value


def _register_blueprints(app):
    from routes.admin import admin_bp
    from routes.auth import auth_bp
    from routes.games.drawing import drawing_bp
    from routes.games.noise import noise_bp
    from routes.games.runner import runner_bp
    from routes.games.voices import voices_bp
    from routes.home import home_bp
    from routes.language import language_bp
    from routes.matches import matches_bp
    from routes.models_api import models_bp

    for blueprint in (home_bp, auth_bp, language_bp, matches_bp, admin_bp, models_bp,
                      noise_bp, voices_bp, drawing_bp, runner_bp):
        app.register_blueprint(blueprint)


def _register_template_globals(app):
    local_zone = ZoneInfo(app.games_config.app.timezone)

    @app.url_defaults
    def static_version(endpoint, values):
        """Every static URL carries the file's modification time (?v=...).
        Cloudflare tells browsers to cache JS/CSS for hours; with the version
        in the URL an updated file is a new URL, so a page never runs with a
        stale script."""
        if endpoint == "static" and "filename" in values:
            path = os.path.join(app.static_folder, values["filename"])
            values["v"] = int(os.stat(path).st_mtime)

    @app.template_filter("localdt")
    def localdt(value, fmt="%d/%m/%Y %H:%M"):
        """DB datetimes are naive UTC (SQLite drops the tzinfo); show local time."""
        return value.replace(tzinfo=timezone.utc).astimezone(local_zone).strftime(fmt)

    @app.template_filter("pts")
    def pts(value, sign=False):
        """Points in the UI language: 5, 2,5 (it) / 2.5 (en); sign=True adds +."""
        value = clean_points(value)
        text = str(abs(value) if sign else value)
        if get_locale() == "it":
            text = text.replace(".", ",")
        if sign:
            text = ("-" if value < 0 else "+") + text
        return text

    @app.context_processor
    def inject_globals():
        match = get_current_match() if current_user.is_authenticated else None
        return {
            "app_name": app.games_config.app.name,
            "t": t,
            "localized": localized,
            "locale": get_locale(),
            "games": GAMES,
            "current_match": match,
            # Games finished in the current match (game bar: finish / reopen).
            "current_finished_games": finished_games(match) if match is not None else set(),
        }


def _register_error_handlers(app):
    # Game pages call JSON endpoints under /api/; an exception there must
    # come back as JSON, not an HTML error page the JS can't parse.
    def _is_api_request():
        return "/api/" in request.path

    @app.errorhandler(403)
    def forbidden(_error):
        if _is_api_request():
            return jsonify({"error": t("errors.forbidden")}), 403
        return render_template("errors/error.html", code=403, heading=t("errors.403_heading"),
                               body=t("errors.403_body")), 403

    @app.errorhandler(404)
    def not_found(_error):
        if _is_api_request():
            return jsonify({"error": t("errors.api_not_found")}), 404
        return render_template("errors/error.html", code=404, heading=t("errors.404_heading"),
                               body=t("errors.404_body")), 404

    @app.errorhandler(GameFinishedError)
    def game_finished(error):
        message = t("game.finished_locked", game=t(f"games.{error.game}.title"))
        if _is_api_request():
            return jsonify({"error": message}), 409
        flash(message, "error")
        next_path = request.form.get("next", "")
        if next_path.startswith("/") and not next_path.startswith("//"):
            return redirect(next_path)
        return redirect(url_for("home.index"))

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify({"error": t("errors.too_large")}), 413

    @app.errorhandler(500)
    def server_error(error):
        app.logger.exception("Unhandled server error", exc_info=error)
        if _is_api_request():
            return jsonify({"error": t("errors.api_server_error")}), 500
        return render_template("errors/error.html", code=500, heading=t("errors.500_heading"),
                               body=t("errors.500_body")), 500


def _register_cli_commands(app):
    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(username, password):
        """Create the first admin (or reset an existing account to admin + new password).
        Further accounts are managed from the admin panel."""
        user = User.find_by_username(username)
        if user is None:
            user = User(username=username.strip(), role=ROLE_ADMIN)
            db.session.add(user)
        user.role = ROLE_ADMIN
        user.enabled = True
        user.set_password(password)
        db.session.commit()
        click.echo(f"Admin {user.username!r} ready.")

    @app.cli.command("seed-content")
    def seed_content():
        """Load the default content of every game (skips games that already have content)."""
        from content import seed_all

        for line in seed_all():
            click.echo(line)


def build():
    config_path = os.environ.get("AI_GAMES_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    return create_app(load_config(config_path=config_path, args=[]), config_path)


if __name__ == "__main__":
    _config_path = os.environ.get("AI_GAMES_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    _config = load_config(config_path=_config_path)
    application = create_app(_config, _config_path)
    application.run(host=_config.server.host, port=_config.server.port, debug=_config.server.debug,
                    threaded=True, use_reloader=False)
