"""Default game content, loaded with `flask --app app:build seed-content`.

Each game with editable content has a module here exposing seed() -> str.
Seeding a game is skipped if it already has content, so re-running the
command never duplicates or overwrites what admins have edited.
"""

from content import drawing, noise, voices


def seed_all():
    return [noise.seed(), voices.seed(), drawing.seed()]
