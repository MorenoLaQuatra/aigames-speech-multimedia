"""Shared Flask extension instances, kept apart from app.py/models.py to
avoid circular imports."""

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
# No "please log in" flash: the login page speaks for itself, and the
# default message would be English-only.
login_manager.login_message = None
csrf = CSRFProtect()
