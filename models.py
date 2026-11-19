"""SQLAlchemy models for AI Games.

Three groups:
- Accounts: User (role "admin" or "instructor", can be deactivated).
- Matches: Match -> Team -> ScoreEvent (+ GameFinish: games closed in the
  match). A match is one group of teams
  playing the four games (typically one school class visit). Teams belong to
  exactly one match, so two matches can both have a team called "Rossi"
  without sharing anything. ScoreEvent is the single source of truth for
  every leaderboard (services/scoring.py).
- Game content (editable by admins) and per-match game state.
"""

import json
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


def utcnow():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

ROLE_ADMIN = "admin"
ROLE_INSTRUCTOR = "instructor"
ROLES = (ROLE_ADMIN, ROLE_INSTRUCTOR)


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False, default="")
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_INSTRUCTOR)
    # Named `enabled` rather than `active` so it doesn't shadow UserMixin's
    # `is_active` property, which Flask-Login checks on every request.
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    theme = db.Column(db.String(10), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_active(self):
        return self.enabled

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def display_name(self):
        return self.full_name or self.username

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def find_by_username(username):
        return User.query.filter(db.func.lower(User.username) == username.strip().lower()).first()


# --------------------------------------------------------------------------
# Matches, teams, scores
# --------------------------------------------------------------------------

MATCH_ACTIVE = "active"
MATCH_ARCHIVED = "archived"

# Flat, distinguishable team colours (also used on the projector view).
TEAM_COLORS = ["#3F817C", "#F5B91D", "#C8102E", "#2F6DB5", "#7A4FA3", "#E07B24", "#0C3734", "#6B6B6B"]


class Match(db.Model):
    __tablename__ = "matches"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    school = db.Column(db.String(160), nullable=False, default="")
    notes = db.Column(db.Text, nullable=False, default="")
    play_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=MATCH_ACTIVE, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    archived_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship("User")
    teams = db.relationship(
        "Team", back_populates="match", order_by="Team.position", cascade="all, delete-orphan"
    )

    @property
    def is_archived(self):
        return self.status == MATCH_ARCHIVED


class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    color = db.Column(db.String(7), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)

    match = db.relationship("Match", back_populates="teams")


class ScoreEvent(db.Model):
    """One scoring event. Leaderboards are sums of these.

    `ref` identifies events that must be unique (e.g. "drawing:challenge:4" -
    re-confirming a drawing replaces the previous score instead of adding a
    second one); it is NULL for append-only events such as each noise
    attempt. `detail` is a JSON blob for display/audit only.
    """

    __tablename__ = "score_events"

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True)
    game = db.Column(db.String(20), nullable=False, index=True)
    # Float: some games award fractions (voices: 2.5 per right answer). The
    # SQLite column was created as INTEGER; SQLite keeps non-whole values
    # as REAL in it, so no migration is needed.
    points = db.Column(db.Float, nullable=False)
    ref = db.Column(db.String(80), nullable=True, index=True)
    detail_json = db.Column(db.Text, nullable=False, default="{}")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    team = db.relationship("Team")

    @property
    def detail(self):
        return json.loads(self.detail_json)


class GameFinish(db.Model):
    """A game the instructor has finished ("Concludi gioco") in a match: its
    scores are locked (services/scoring.py add_score) and its results can be
    shown on the projector. Deleting the row reopens the game."""

    __tablename__ = "game_finishes"
    __table_args__ = (db.UniqueConstraint("match_id", "game"),)

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False, index=True)
    game = db.Column(db.String(20), nullable=False)
    finished_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    finished_at = db.Column(db.DateTime, nullable=False, default=utcnow)


# --------------------------------------------------------------------------
# Game content (admin-editable). Every content table has `active` so content
# can be retired without deleting the history that refers to it.
# --------------------------------------------------------------------------

NOISE_ANIMALS = "animals"
NOISE_HUMAN = "human"
NOISE_OTHER = "other"
NOISE_CATEGORIES = (NOISE_ANIMALS, NOISE_HUMAN, NOISE_OTHER)


class NoiseTarget(db.Model):
    """Game 1: a sound to imitate. `labels` lists the AudioSet class names
    (one per line) that count as recognising it. `category` (NOISE_CATEGORIES)
    groups sounds of similar difficulty: teams draw from one category at a time."""

    __tablename__ = "noise_targets"

    id = db.Column(db.Integer, primary_key=True)
    name_it = db.Column(db.String(80), nullable=False)
    name_en = db.Column(db.String(80), nullable=False)
    emoji = db.Column(db.String(16), nullable=False, default="")
    category = db.Column(db.String(20), nullable=False, default=NOISE_OTHER, server_default=NOISE_OTHER)
    labels = db.Column(db.Text, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def label_list(self):
        return [line.strip() for line in self.labels.splitlines() if line.strip()]


class VoicePhrase(db.Model):
    """Game 2: a sentence the cloned voices will say."""

    __tablename__ = "voice_phrases"

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(300), nullable=False)
    language = db.Column(db.String(5), nullable=False, default="it")
    active = db.Column(db.Boolean, nullable=False, default=True)


# Shorter words of an element's name (a, da, di, of...) are not forbidden.
MIN_ELEMENT_WORD_LETTERS = 3


class DrawingChallenge(db.Model):
    """Game 3: describe a scene without the forbidden words.

    elements_json: [{"it": "cane", "en": "dog", "query": "a dog"}, ...] -
      the things that earn points if the detector finds them in the image.
    forbidden_words: one word per line (Italian and English forms), on top
      of the elements' own names, which are always forbidden (forbidden_list).
    """

    __tablename__ = "drawing_challenges"

    id = db.Column(db.Integer, primary_key=True)
    title_it = db.Column(db.String(120), nullable=False)
    title_en = db.Column(db.String(120), nullable=False)
    brief_it = db.Column(db.Text, nullable=False, default="")
    brief_en = db.Column(db.Text, nullable=False, default="")
    elements_json = db.Column(db.Text, nullable=False, default="[]")
    forbidden_words = db.Column(db.Text, nullable=False, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def elements(self):
        return json.loads(self.elements_json)

    @property
    def forbidden_list(self):
        """Every forbidden word: each word (3+ letters) of the elements'
        Italian and English names - the point of the game is to get them
        drawn without naming them ("sedia a sdraio" forbids sedia and
        sdraio, not "a") - then the listed ones, without duplicates."""
        words = []
        for element in self.elements:
            for name in (element["it"], element["en"]):
                words.extend(word for word in name.split() if len(word) >= MIN_ELEMENT_WORD_LETTERS)
        words.extend(line.strip() for line in self.forbidden_words.splitlines() if line.strip())
        unique = {}
        for word in words:
            unique.setdefault(word.lower(), word)
        return list(unique.values())


# --------------------------------------------------------------------------
# Per-match game state
# --------------------------------------------------------------------------

class VoiceVolunteer(db.Model):
    """Game 2: a volunteer whose voice gets cloned. The reference recording
    lives under storage.media_dir and is deleted when the match is archived."""

    __tablename__ = "voice_volunteers"

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True)
    nickname = db.Column(db.String(60), nullable=False)
    reference_path = db.Column(db.String(400), nullable=True)
    # Set when the instructor confirmed consent before recording (only
    # required when games.voices.require_consent is true).
    consent_confirmed_at = db.Column(db.DateTime, nullable=True)
    consent_confirmed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    team = db.relationship("Team")


CLIP_PENDING = "pending"
CLIP_READY = "ready"
CLIP_FAILED = "failed"


class VoiceClip(db.Model):
    """Game 2: one round - a phrase said by a cloned volunteer's voice."""

    __tablename__ = "voice_clips"

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False, index=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("voice_volunteers.id"), nullable=False)
    round_number = db.Column(db.Integer, nullable=False)
    phrase_text = db.Column(db.String(300), nullable=False)
    language = db.Column(db.String(5), nullable=False)
    audio_path = db.Column(db.String(400), nullable=True)
    status = db.Column(db.String(20), nullable=False, default=CLIP_PENDING)
    error = db.Column(db.Text, nullable=True)
    revealed = db.Column(db.Boolean, nullable=False, default=False)

    volunteer = db.relationship("VoiceVolunteer")


class VoiceGuess(db.Model):
    __tablename__ = "voice_guesses"
    __table_args__ = (db.UniqueConstraint("clip_id", "team_id"),)

    id = db.Column(db.Integer, primary_key=True)
    clip_id = db.Column(db.Integer, db.ForeignKey("voice_clips.id"), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    guessed_volunteer_id = db.Column(db.Integer, db.ForeignKey("voice_volunteers.id"), nullable=False)


class DrawingAttempt(db.Model):
    """Game 3: one generated image for a team."""

    __tablename__ = "drawing_attempts"

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False, index=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("drawing_challenges.id"), nullable=False)
    prompt_text = db.Column(db.Text, nullable=False)
    translated_text = db.Column(db.Text, nullable=False, default="")
    image_path = db.Column(db.String(400), nullable=True)
    # {"<element index>": {"found": bool, "score": float, "box": [x0,y0,x1,y1] | null}}
    detections_json = db.Column(db.Text, nullable=False, default="{}")
    # Element indices the instructor confirmed (may override the detector).
    confirmed_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    team = db.relationship("Team")
    challenge = db.relationship("DrawingChallenge")

    @property
    def detections(self):
        return json.loads(self.detections_json)

    @property
    def confirmed(self):
        return None if self.confirmed_json is None else json.loads(self.confirmed_json)
