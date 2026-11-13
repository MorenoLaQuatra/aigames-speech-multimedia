"""Login, logout, own account (password change, theme). No self-registration:
admins create accounts from the admin panel."""

from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, EqualTo, Length

from extensions import db
from i18n import t
from models import User

auth_bp = Blueprint("auth", __name__)

MIN_PASSWORD_LENGTH = 8


def _safe_next_url():
    """Only follow ?next= back into this app (no open redirect)."""
    target = request.args.get("next")
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


class LoginForm(FlaskForm):
    username = StringField(validators=[DataRequired()])
    password = PasswordField(validators=[DataRequired()])


class PasswordForm(FlaskForm):
    current_password = PasswordField(validators=[DataRequired()])
    new_password = PasswordField(validators=[DataRequired(), Length(min=MIN_PASSWORD_LENGTH)])
    confirm_password = PasswordField(validators=[DataRequired(), EqualTo("new_password")])


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.find_by_username(form.username.data)
        if user and user.check_password(form.password.data):
            if not user.enabled:
                flash(t("auth.account_disabled"), "error")
                return render_template("auth/login.html", form=form)
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            login_user(user)
            return redirect(_safe_next_url() or url_for("home.index"))
        # Same message whichever part was wrong: no probing for usernames.
        flash(t("auth.wrong_credentials"), "error")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash(t("auth.logged_out"), "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    form = PasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash(t("auth.wrong_current_password"), "error")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash(t("auth.password_changed"), "success")
            return redirect(url_for("auth.account"))
    elif request.method == "POST":
        flash(t("auth.password_invalid", n=MIN_PASSWORD_LENGTH), "error")
    return render_template("auth/account.html", form=form, min_length=MIN_PASSWORD_LENGTH)


@auth_bp.route("/account/theme", methods=["POST"])
@login_required
def save_theme():
    theme = request.form.get("theme", "")
    if theme in ("light", "dark"):
        current_user.theme = theme
        db.session.commit()
    return ("", 204)
