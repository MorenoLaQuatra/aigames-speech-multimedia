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
from models import NOISE_ANIMALS, NOISE_HUMAN, NOISE_OTHER, NoiseTarget

_LABELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audioset_labels.json")

with open(_LABELS_PATH, encoding="utf-8") as _f:
    AUDIOSET_LABELS = json.load(_f)
_LABEL_SET = set(AUDIOSET_LABELS)


def unknown_labels(labels):
    """Labels that are not AudioSet class names (case-sensitive, exact)."""
    return [label for label in labels if label not in _LABEL_SET]


# (name_it, name_en, emoji, category, [AudioSet labels])
DEFAULT_TARGETS = [
    ("Cane", "Dog", "🐕", NOISE_ANIMALS, ["Dog", "Bark", "Bow-wow", "Yip", "Growling"]),
    ("Gatto", "Cat", "🐈", NOISE_ANIMALS, ["Cat", "Meow", "Purr", "Hiss"]),
    ("Gallo", "Rooster", "🐓", NOISE_ANIMALS, ["Chicken, rooster", "Crowing, cock-a-doodle-doo", "Cluck"]),
    ("Mucca", "Cow", "🐄", NOISE_ANIMALS, ["Cattle, bovinae", "Moo"]),
    ("Pecora", "Sheep", "🐑", NOISE_ANIMALS, ["Sheep", "Bleat", "Goat"]),
    ("Maiale", "Pig", "🐖", NOISE_ANIMALS, ["Pig", "Oink"]),
    ("Cavallo", "Horse", "🐎", NOISE_ANIMALS, ["Horse", "Neigh, whinny", "Clip-clop"]),
    ("Anatra", "Duck", "🦆", NOISE_ANIMALS, ["Duck", "Quack"]),
    ("Rana", "Frog", "🐸", NOISE_ANIMALS, ["Frog", "Croak"]),
    ("Leone", "Lion", "🦁", NOISE_ANIMALS, ["Roaring cats (lions, tigers)", "Roar", "Growling"]),
    ("Lupo che ulula", "Howling wolf", "🐺", NOISE_ANIMALS, ["Howl"]),
    ("Gufo", "Owl", "🦉", NOISE_ANIMALS, ["Owl", "Hoot"]),
    ("Uccellino", "Little bird", "🐦", NOISE_ANIMALS, ["Bird vocalization, bird call, bird song", "Chirp, tweet", "Bird"]),
    ("Sirena", "Siren", "🚨", NOISE_OTHER, ["Siren", "Police car (siren)", "Ambulance (siren)", "Fire engine, fire truck (siren)", "Emergency vehicle"]),
    ("Clacson", "Car horn", "🚗", NOISE_OTHER, ["Vehicle horn, car horn, honking", "Car alarm"]),
    ("Treno", "Train", "🚂", NOISE_OTHER, ["Train", "Train whistle", "Train horn", "Steam whistle"]),
    ("Elicottero", "Helicopter", "🚁", NOISE_OTHER, ["Helicopter"]),
    ("Moto", "Motorbike", "🏍️", NOISE_OTHER, ["Motorcycle", "Accelerating, revving, vroom", "Engine"]),
    ("Campanello", "Doorbell", "🔔", NOISE_OTHER, ["Doorbell", "Ding-dong"]),
    ("Telefono che squilla", "Ringing phone", "📞", NOISE_OTHER, ["Telephone bell ringing", "Ringtone", "Telephone"]),
    ("Starnuto", "Sneeze", "🤧", NOISE_HUMAN, ["Sneeze"]),
    ("Tosse", "Cough", "😷", NOISE_HUMAN, ["Cough"]),
    ("Russare", "Snoring", "😴", NOISE_HUMAN, ["Snoring"]),
    ("Risata", "Laughter", "😂", NOISE_HUMAN, ["Laughter", "Giggle", "Belly laugh", "Chuckle, chortle"]),
    ("Fischio", "Whistling", "😗", NOISE_HUMAN, ["Whistling", "Whistle"]),
    ("Orologio", "Ticking clock", "⏰", NOISE_OTHER, ["Tick-tock", "Tick", "Clock"]),
    ("Zanzara", "Mosquito", "🦟", NOISE_ANIMALS, ["Mosquito", "Buzz", "Insect", "Fly, housefly"]),
    ("Neonato che piange", "Crying baby", "👶", NOISE_HUMAN, ["Baby cry, infant cry", "Crying, sobbing"]),
]


def seed():
    if NoiseTarget.query.first() is not None:
        return "noise: targets already present, skipped"
    for name_it, name_en, emoji, category, labels in DEFAULT_TARGETS:
        bad = unknown_labels(labels)
        if bad:
            raise ValueError(f"noise seed: unknown AudioSet labels for {name_en!r}: {bad}")
        db.session.add(NoiseTarget(name_it=name_it, name_en=name_en, emoji=emoji, category=category,
                                   labels="\n".join(labels)))
    db.session.commit()
    return f"noise: {len(DEFAULT_TARGETS)} targets added"


def backfill_categories():
    """One-off upgrade: databases created before categories existed got
    category "other" for every sound; give the default sounds their category.
    Returns the number of sounds changed."""
    by_name = {name_en: category for _, name_en, _, category, _ in DEFAULT_TARGETS}
    changed = 0
    for target in NoiseTarget.query.all():
        category = by_name.get(target.name_en)
        if category and target.category != category:
            target.category = category
            changed += 1
    db.session.commit()
    return changed
