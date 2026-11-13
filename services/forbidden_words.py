"""Forbidden-word check for the drawing game.

A word in the description is forbidden if, after normalising (lowercase,
accents stripped), it equals a forbidden word or has the same rough stem:
  - Italian: one trailing vowel (a/e/i/o) is dropped from words of 4+
    letters, so cane/cani and gatto/gatti/gatta collide, while canzone
    (stem "canzon") does not collide with cane (stem "can");
  - English: a trailing "es"/"s" is dropped, so dog/dogs and box/boxes collide.
Only the forbidden list is checked - content authors list every form they
want to forbid that the stemming doesn't catch (e.g. cagnolino).

static/js/drawing.js mirrors these rules for live highlighting; this module
is authoritative (the server rejects the attempt).
"""

import re
import unicodedata

_TOKEN = re.compile(r"[a-z]+")
_IT_VOWELS = ("a", "e", "i", "o")


def normalize(text):
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokenize(text):
    return _TOKEN.findall(normalize(text))


def stems(word):
    """All the stems a word may reduce to (Italian and English rules)."""
    out = {word}
    if len(word) >= 4 and word.endswith(_IT_VOWELS):
        out.add(word[:-1])
    if len(word) >= 4 and word.endswith("es"):
        out.add(word[:-2])
    if len(word) >= 4 and word.endswith("s"):
        out.add(word[:-1])
    return out


def find_forbidden(text, forbidden_words):
    """Forbidden words (as listed) that the text uses, in list order."""
    used_stems = set()
    for token in tokenize(text):
        used_stems |= stems(token)
    hits = []
    for word in forbidden_words:
        for part in tokenize(word):
            if stems(part) & used_stems:
                hits.append(word)
                break
    return hits


if __name__ == "__main__":
    assert find_forbidden("Un cane che corre", ["cane"]) == ["cane"]
    assert find_forbidden("Due cani nel prato", ["cane"]) == ["cane"]
    assert find_forbidden("Una gatta e due gatti", ["gatto"]) == ["gatto"]
    assert find_forbidden("Ascolto una canzone", ["cane"]) == []
    assert find_forbidden("Two dogs and a box", ["dog", "boxes"]) == ["dog", "boxes"]
    assert find_forbidden("Il CAFFÈ è caldo", ["caffe"]) == ["caffe"]
    assert find_forbidden("La spiaggia al tramonto", ["mare", "sea"]) == []
    assert find_forbidden("Un ombrellone colorato", ["ombrellone"]) == ["ombrellone"]
    assert find_forbidden("Il sole splende", ["sole", "sun"]) == ["sole"]
    assert find_forbidden("Una solenne cerimonia", ["sole"]) == []
    print("forbidden_words: all checks passed")
