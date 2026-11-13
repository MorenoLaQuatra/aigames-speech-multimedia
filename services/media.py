"""Per-match media files (voice recordings, cloned clips, generated images).

Everything for a match lives under <storage.media_dir>/match-<id>/, so
deleting a match's personal data on archive is a single rmtree.
"""

import os
import shutil
import uuid

from flask import current_app


def match_dir(match_id):
    path = os.path.join(current_app.root_path, current_app.games_config.storage.media_dir, f"match-{match_id}")
    os.makedirs(path, exist_ok=True)
    return path


def new_media_path(match_id, kind, extension):
    """A fresh, unguessable file path for a match, e.g. kind="voice-ref"."""
    return os.path.join(match_dir(match_id), f"{kind}-{uuid.uuid4().hex}.{extension}")


def is_inside_media_dir(path):
    root = os.path.realpath(os.path.join(current_app.root_path, current_app.games_config.storage.media_dir))
    return os.path.realpath(path).startswith(root + os.sep)


def delete_match_media(match_id):
    path = os.path.join(current_app.root_path, current_app.games_config.storage.media_dir, f"match-{match_id}")
    if os.path.isdir(path):
        shutil.rmtree(path)
