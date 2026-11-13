"""Language switch (IT/EN), session based. Not login-gated so the login page
can be switched too."""

from flask import Blueprint, redirect, request, url_for

from i18n import SUPPORTED_LOCALES, set_locale

language_bp = Blueprint("language", __name__)


@language_bp.route("/set-language", methods=["POST"])
def set_language():
    code = request.form.get("locale", "")
    if code in SUPPORTED_LOCALES:
        set_locale(code)
    next_path = request.form.get("next", "")
    if next_path.startswith("/") and not next_path.startswith("//"):
        return redirect(next_path)
    return redirect(url_for("home.index"))
