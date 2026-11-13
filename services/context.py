"""The "current match" an instructor is running, kept in the session.

Every game page works on the current match. Instructors pick it on the
dashboard or the matches page; archived matches can be viewed but never be
the current match (they are read-only).
"""

from functools import wraps

from flask import abort, flash, redirect, session, url_for
from flask_login import current_user

from extensions import db
from i18n import t
from models import MATCH_ACTIVE, Match

_SESSION_KEY = "current_match_id"


def get_current_match():
    match_id = session.get(_SESSION_KEY)
    if match_id is None:
        return None
    match = db.session.get(Match, match_id)
    if match is None or match.status != MATCH_ACTIVE:
        session.pop(_SESSION_KEY, None)
        return None
    return match


def set_current_match(match):
    session[_SESSION_KEY] = match.id


def clear_current_match():
    session.pop(_SESSION_KEY, None)


def require_current_match(view):
    """Game pages: redirect to the matches page if no active match is selected.
    The match is passed to the view as `match=`."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        match = get_current_match()
        if match is None:
            flash(t("matches.select_first"), "info")
            return redirect(url_for("matches.index"))
        if not match.teams:
            flash(t("matches.add_teams_first"), "info")
            return redirect(url_for("matches.detail", match_id=match.id))
        return view(*args, match=match, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper
