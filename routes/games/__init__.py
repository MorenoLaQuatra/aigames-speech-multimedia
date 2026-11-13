"""Registry of the four games. The dashboard, results pages and admin
content panel are all driven by this list.

Each game lives in routes/games/<slug>.py as a blueprint named `<slug>_bp`
with at least:
  <slug>.play     - the game page for the current match
  <slug>.content  - the admin page for editing the game's content
and its strings in i18n/<slug>.py (games.<slug>.title / .short / .description).
`worker` is the model process it needs (configs/app.yaml: models.workers),
or None when the model runs in the browser.
"""

GAMES = [
    {"slug": "noise", "icon": "fa-dog", "worker": "audio_classifier"},
    {"slug": "voices", "icon": "fa-user-secret", "worker": "voice_clone"},
    {"slug": "drawing", "icon": "fa-palette", "worker": "image_gen"},
    {"slug": "runner", "icon": "fa-person-running", "worker": None},
]

GAMES_BY_SLUG = {game["slug"]: game for game in GAMES}
