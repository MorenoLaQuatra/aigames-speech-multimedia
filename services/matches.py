"""Permanent deletion of a match (admins, from the UI).

Removes the match with everything that belongs to it: teams, scores, finished
games, voice volunteers/clips/guesses, drawing attempts, and its media files
on disk (recordings, cloned clips, generated images).
"""

from extensions import db
from models import (DrawingAttempt, GameFinish, ScoreEvent, VoiceClip, VoiceGuess,
                    VoiceVolunteer)
from services.media import delete_match_media


def delete_match(match):
    """Delete `match` and all its rows and files; commits. Returns its name."""
    name = match.name
    clip_ids = [clip.id for clip in VoiceClip.query.filter_by(match_id=match.id)]
    if clip_ids:
        VoiceGuess.query.filter(VoiceGuess.clip_id.in_(clip_ids)).delete(synchronize_session=False)
    VoiceClip.query.filter_by(match_id=match.id).delete()
    VoiceVolunteer.query.filter_by(match_id=match.id).delete()
    DrawingAttempt.query.filter_by(match_id=match.id).delete()
    ScoreEvent.query.filter_by(match_id=match.id).delete()
    GameFinish.query.filter_by(match_id=match.id).delete()
    db.session.delete(match)  # teams go with it (cascade)
    db.session.commit()
    delete_match_media(match.id)  # files last: the rows are gone even if this fails
    return name
