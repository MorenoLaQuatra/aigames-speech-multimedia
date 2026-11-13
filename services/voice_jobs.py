"""Background generation of the cloned clips for game 2 ("voices").

Cloning is slow (seconds on GPU, ~half a minute per clip on CPU), so clips
are generated one at a time in a background thread while the instructor
keeps playing: round 1 can start as soon as its clip is ready.

One thread per match at most. The thread makes sure the voice_clone worker
is running, then repeatedly takes the pending clip with the lowest round
number, sends it to the worker and stores the result. A clip that fails is
marked failed (with the error) and the thread moves on; the page offers a
"retry failed clips" button that puts them back to pending and restarts it.
"""

import logging
import threading
import time

import requests

from extensions import db
from models import CLIP_FAILED, CLIP_PENDING, CLIP_READY, VoiceClip
from services.media import new_media_path
from services.model_manager import STATUS_FAILED, STATUS_READY, WorkerUnavailable

log = logging.getLogger(__name__)

WORKER = "voice_clone"
POLL_SECONDS = 2

_lock = threading.Lock()
_threads = {}  # match_id -> Thread


def is_running(match_id):
    with _lock:
        thread = _threads.get(match_id)
        return thread is not None and thread.is_alive()


def start(app, match_id):
    """Start the generation thread for a match unless one is already running."""
    with _lock:
        thread = _threads.get(match_id)
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(target=_run, args=(app, match_id), name=f"voice-job-{match_id}", daemon=True)
        _threads[match_id] = thread
        thread.start()


def _run(app, match_id):
    # Hold the worker for the whole job, so opening another game's page
    # (which starts its own model) can't stop it between clips.
    with app.app_context(), app.models.hold(WORKER):
        if not _wait_for_worker(app):
            _fail_all_pending(match_id, "voice model failed to start - see logs/worker-voice_clone.log")
            return
        while True:
            clip = (VoiceClip.query.filter_by(match_id=match_id, status=CLIP_PENDING)
                    .order_by(VoiceClip.round_number.asc()).first())
            if clip is None:
                return
            _generate(app, clip)
            db.session.remove()


def _wait_for_worker(app):
    manager = app.models
    manager.ensure_started(WORKER)
    deadline = time.time() + manager.workers[WORKER].cfg.startup_timeout_seconds + 30
    while time.time() < deadline:
        status = manager.status(WORKER)["status"]
        if status == STATUS_READY:
            return True
        if status == STATUS_FAILED:
            return False
        time.sleep(POLL_SECONDS)
    return False


def _generate(app, clip):
    cfg = app.games_config.games.voices
    volunteer = clip.volunteer
    try:
        if volunteer.reference_path is None:
            raise RuntimeError("volunteer has no reference recording")
        with open(volunteer.reference_path, "rb") as reference:
            response = app.models.post(
                WORKER, "/clone",
                data={"text": clip.phrase_text, "language": clip.language, "exaggeration": str(cfg.exaggeration)},
                files={"reference_audio": ("reference.wav", reference, "audio/wav")},
            )
        path = new_media_path(clip.match_id, "voice-clip", "wav")
        with open(path, "wb") as out:
            out.write(response.content)
        clip.audio_path = path
        clip.status = CLIP_READY
        clip.error = None
    # The one place a broad catch is acceptable: one clip failing must not
    # stop the others; the error is logged and shown next to the clip.
    except (WorkerUnavailable, requests.RequestException, OSError, RuntimeError) as exc:
        log.exception("Voice clip %s failed", clip.id)
        clip.status = CLIP_FAILED
        clip.error = str(exc) or exc.__class__.__name__
    db.session.commit()


def _fail_all_pending(match_id, message):
    VoiceClip.query.filter_by(match_id=match_id, status=CLIP_PENDING).update(
        {"status": CLIP_FAILED, "error": message})
    db.session.commit()
