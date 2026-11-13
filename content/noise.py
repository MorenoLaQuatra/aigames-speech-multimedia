"""Default content for game 1 ("noise"): sounds to imitate.

Each target lists the AudioSet classes that count as "recognised". Every
label must be an exact class name of the classifier; audioset_labels.json
(next to this file) holds the 527 names, generated from the model config of
MIT/ast-finetuned-audioset-10-10-0.4593, so labels can be validated without
starting the model.
"""

import json
import os

from extensions import db
from models import NoiseTarget

_LABELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audioset_labels.json")

with open(_LABELS_PATH, encoding="utf-8") as _f:
    AUDIOSET_LABELS = json.load(_f)
_LABEL_SET = set(AUDIOSET_LABELS)


def unknown_labels(labels):
    """Labels that are not AudioSet class names (case-sensitive, exact)."""
    return [label for label in labels if label not in _LABEL_SET]


# (name_it, name_en, emoji, [AudioSet labels])
DEFAULT_TARGETS = [
    ("Cane", "Dog", "🐕", ["Dog", "Bark", "Bow-wow", "Yip", "Growling"]),
    ("Gatto", "Cat", "🐈", ["Cat", "Meow", "Purr", "Hiss"]),
    ("Gallo", "Rooster", "🐓", ["Chicken, rooster", "Crowing, cock-a-doodle-doo", "Cluck"]),
    ("Mucca", "Cow", "🐄", ["Cattle, bovinae", "Moo"]),
    ("Pecora", "Sheep", "🐑", ["Sheep", "Bleat", "Goat"]),
    ("Maiale", "Pig", "🐖", ["Pig", "Oink"]),
    ("Cavallo", "Horse", "🐎", ["Horse", "Neigh, whinny", "Clip-clop"]),
    ("Anatra", "Duck", "🦆", ["Duck", "Quack"]),
    ("Rana", "Frog", "🐸", ["Frog", "Croak"]),
    ("Leone", "Lion", "🦁", ["Roaring cats (lions, tigers)", "Roar", "Growling"]),
    ("Lupo che ulula", "Howling wolf", "🐺", ["Howl"]),
    ("Gufo", "Owl", "🦉", ["Owl", "Hoot"]),
    ("Uccellino", "Little bird", "🐦", ["Bird vocalization, bird call, bird song", "Chirp, tweet", "Bird"]),
    ("Sirena", "Siren", "🚨", ["Siren", "Police car (siren)", "Ambulance (siren)", "Fire engine, fire truck (siren)", "Emergency vehicle"]),
    ("Clacson", "Car horn", "🚗", ["Vehicle horn, car horn, honking", "Car alarm"]),
    ("Treno", "Train", "🚂", ["Train", "Train whistle", "Train horn", "Steam whistle"]),
    ("Elicottero", "Helicopter", "🚁", ["Helicopter"]),
    ("Moto", "Motorbike", "🏍️", ["Motorcycle", "Accelerating, revving, vroom", "Engine"]),
    ("Campanello", "Doorbell", "🔔", ["Doorbell", "Ding-dong"]),
    ("Telefono che squilla", "Ringing phone", "📞", ["Telephone bell ringing", "Ringtone", "Telephone"]),
    ("Starnuto", "Sneeze", "🤧", ["Sneeze"]),
    ("Tosse", "Cough", "😷", ["Cough"]),
    ("Russare", "Snoring", "😴", ["Snoring"]),
    ("Risata", "Laughter", "😂", ["Laughter", "Giggle", "Belly laugh", "Chuckle, chortle"]),
    ("Fischio", "Whistling", "😗", ["Whistling", "Whistle"]),
    ("Orologio", "Ticking clock", "⏰", ["Tick-tock", "Tick", "Clock"]),
    ("Zanzara", "Mosquito", "🦟", ["Mosquito", "Buzz", "Insect", "Fly, housefly"]),
    ("Neonato che piange", "Crying baby", "👶", ["Baby cry, infant cry", "Crying, sobbing"]),
]


def seed():
    if NoiseTarget.query.first() is not None:
        return "noise: targets already present, skipped"
    for name_it, name_en, emoji, labels in DEFAULT_TARGETS:
        bad = unknown_labels(labels)
        if bad:
            raise ValueError(f"noise seed: unknown AudioSet labels for {name_en!r}: {bad}")
        db.session.add(NoiseTarget(name_it=name_it, name_en=name_en, emoji=emoji, labels="\n".join(labels)))
    db.session.commit()
    return f"noise: {len(DEFAULT_TARGETS)} targets added"
