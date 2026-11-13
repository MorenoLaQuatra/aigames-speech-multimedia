"""Minimal i18n: flat translation dicts per locale, Italian by default.

Strings are split per area so each game owns its own copy:
  i18n/core.py     - shared chrome (nav, auth, matches, admin, results)
  i18n/<game>.py   - one module per game
Each module defines STRINGS = {"it": {...}, "en": {...}}. They are merged
here at import time; a key defined twice, or present in one locale but not
the other, raises immediately rather than showing a raw key on screen.

Usage:
  - Templates: {{ t('nav.dashboard') }} (Jinja global, see app.py).
  - Python:    from i18n import t
  - JS:        each page passes the strings its script needs through its
               inline JSON config (see templates/games/*.html).
"""

from flask import has_request_context, session

from i18n import core, drawing, noise, runner, voices

SUPPORTED_LOCALES = ("it", "en")
DEFAULT_LOCALE = "it"

_MODULES = (core, noise, voices, drawing, runner)


def _merge_translations():
    merged = {locale: {} for locale in SUPPORTED_LOCALES}
    for module in _MODULES:
        for locale in SUPPORTED_LOCALES:
            for key, value in module.STRINGS[locale].items():
                if key in merged[locale]:
                    raise RuntimeError(f"Duplicate i18n key {key!r} ({module.__name__}, {locale})")
                merged[locale][key] = value
    it_keys, en_keys = set(merged["it"]), set(merged["en"])
    if it_keys != en_keys:
        raise RuntimeError(
            f"i18n keys differ between locales: only it={sorted(it_keys - en_keys)}, "
            f"only en={sorted(en_keys - it_keys)}"
        )
    return merged


TRANSLATIONS = _merge_translations()


def get_locale():
    if not has_request_context():
        return DEFAULT_LOCALE
    return session.get("locale", DEFAULT_LOCALE)


def set_locale(code):
    session["locale"] = code


def t(key, **kwargs):
    """Translate `key` for the current locale. A missing key raises (fail fast)."""
    text = TRANSLATIONS[get_locale()][key]
    return text.format(**kwargs) if kwargs else text


def localized(obj, field):
    """Pick obj.<field>_<locale> (e.g. name_it / name_en) for bilingual content."""
    return getattr(obj, f"{field}_{get_locale()}")
