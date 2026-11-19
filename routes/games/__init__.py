"""Registry of the four games. The dashboard, results pages and admin
content panel are all driven by this list.

Each game lives in routes/games/<slug>.py as a blueprint named `<slug>_bp`
with at least:
  <slug>.play     - the game page for the current match
  <slug>.content  - the admin page for editing the game's content
and its strings in i18n/<slug>.py (games.<slug>.title / .short / .description).
`worker` is the model process it needs (configs/app.yaml: models.workers),
or None when the model runs in the browser. `image` / `thumb` are the game's
artwork (same pictures as the school flyers; sources in icons-games/, web
versions in static/img/games/), relative to static/.
"""

GAMES = [
    {"slug": "noise", "worker": "audio_classifier"},
    {"slug": "voices", "worker": "voice_clone"},
    {"slug": "drawing", "worker": "image_gen"},
    {"slug": "runner", "worker": None},
]

for _game in GAMES:
    _game["image"] = f"img/games/{_game['slug']}.webp"
    _game["thumb"] = f"img/games/{_game['slug']}-thumb.webp"

GAMES_BY_SLUG = {game["slug"]: game for game in GAMES}
