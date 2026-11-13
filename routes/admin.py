"""Admin panel: accounts, game content (links to each game's own content
page), and the model processes."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Optional

from extensions import db
from i18n import t
from models import ROLE_ADMIN, ROLES, Match, User
from routes.auth import MIN_PASSWORD_LENGTH
from services.context import admin_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


class NewUserForm(FlaskForm):
    username = StringField(validators=[DataRequired(), Length(max=80)])
    full_name = StringField(validators=[Optional(), Length(max=120)])
    password = PasswordField(validators=[DataRequired(), Length(min=MIN_PASSWORD_LENGTH)])
    role = SelectField(choices=[(r, r) for r in ROLES], validators=[DataRequired()])


class ResetPasswordForm(FlaskForm):
    password = PasswordField(validators=[DataRequired(), Length(min=MIN_PASSWORD_LENGTH)])


def _get_user(user_id):
    return User.query.filter_by(id=user_id).first_or_404()


def _active_admin_count():
    return User.query.filter_by(role=ROLE_ADMIN, enabled=True).count()


@admin_bp.route("/")
@login_required
@admin_required
def index():
    return redirect(url_for("admin.users"))


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.enabled.desc(), User.username.asc()).all()
    match_counts = dict(db.session.query(Match.created_by_id, db.func.count(Match.id)).group_by(Match.created_by_id).all())
    return render_template("admin/users.html", users=all_users, form=NewUserForm(), reset_form=ResetPasswordForm(),
                           match_counts=match_counts, min_length=MIN_PASSWORD_LENGTH, roles=ROLES)


@admin_bp.route("/users/new", methods=["POST"])
@login_required
@admin_required
def create_user():
    form = NewUserForm()
    if not form.validate_on_submit():
        flash(t("admin.user_invalid", n=MIN_PASSWORD_LENGTH), "error")
    elif User.find_by_username(form.username.data) is not None:
        flash(t("admin.username_taken"), "error")
    else:
        user = User(username=form.username.data.strip(), full_name=(form.full_name.data or "").strip(),
                    role=form.role.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(t("admin.user_created", username=user.username), "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(user_id):
    user = _get_user(user_id)
    if user.id == current_user.id:
        flash(t("admin.cannot_disable_self"), "error")
    elif user.enabled and user.is_admin and _active_admin_count() <= 1:
        flash(t("admin.last_admin"), "error")
    else:
        user.enabled = not user.enabled
        db.session.commit()
        flash(t("admin.user_enabled" if user.enabled else "admin.user_disabled", username=user.username), "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
@admin_required
def change_role(user_id):
    user = _get_user(user_id)
    role = request.form.get("role", "")
    if role not in ROLES:
        flash(t("admin.user_invalid", n=MIN_PASSWORD_LENGTH), "error")
    elif user.id == current_user.id and role != ROLE_ADMIN:
        flash(t("admin.cannot_demote_self"), "error")
    else:
        user.role = role
        db.session.commit()
        flash(t("common.saved"), "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/password", methods=["POST"])
@login_required
@admin_required
def reset_password(user_id):
    user = _get_user(user_id)
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash(t("admin.password_reset", username=user.username), "success")
    else:
        flash(t("auth.password_invalid", n=MIN_PASSWORD_LENGTH), "error")
    return redirect(url_for("admin.users"))


@admin_bp.route("/content")
@login_required
@admin_required
def content():
    return render_template("admin/content.html")


@admin_bp.route("/models")
@login_required
@admin_required
def models():
    return render_template("admin/models.html")
