# AI Games (UKE)

A Flask webapp to run four team games about artificial intelligence with
school classes visiting UKE (Università degli Studi di Enna "Kore"). An
instructor logs in, creates a **match** (one class visit) with its teams,
plays the four games (~10 minutes each), shows the live standings on a
projector, and archives the match at the end. Italian by default, English
toggle in the header.

| # | Game | What the AI does | Where the model runs |
|---|------|------------------|----------------------|
| 1 | **Sound Challenge** | Audio classifier (AudioSet) recognises imitated noises | `workers/audio_classifier.py` |
| 2 | **Voice Match** | Clones volunteers' voices; teams guess who's speaking | `workers/voice_clone.py` |
| 3 | **Visual Taboo** | Text-to-image from a description without forbidden words; a detector checks which elements appear | `workers/image_gen.py` |
| 4 | **Sound Gaming** | A small network learns each team's 3 command words (recorded push-to-talk) in the browser and drives a runner game | in the browser (TensorFlow.js) |

## One thing to launch

```bash
./start.sh            # gunicorn on configs/app.yaml server.host:server.port (9000)
```

Or as a system service (install once with
`sudo deploy/install-app-service.sh`; not enabled at boot):

```bash
sudo systemctl start ai-games     # activate
sudo systemctl stop ai-games      # deactivate (model workers stop too)
journalctl -u ai-games -f         # log
```

That's it. The webapp starts each **model worker** as a child process the
first time a game page needs it, and stops it again when:
- it has been idle for `models.idle_minutes`, or
- another worker starts and `models.exclusive: true`, unless both workers
  have `share_gpu: true` (audio classifier + voice cloning can run together;
  image generation runs alone), or
- an admin stops it from **Amministrazione > Modelli**, or
- the webapp exits (children die with it, even on `kill -9`).

Game pages show a "model ready / starting" badge; opening a game a minute
before you need it hides the loading time. Worker logs: `logs/worker-<name>.log`.

**Two games at once on two PCs** (e.g. Sound Challenge while volunteers record
for Voice Match): log in on both PCs (the same account is fine), pick the same
match on each, open one game per PC. Points from both go to the same match.
Sound Challenge and Voice Match share the GPU; Visual Taboo needs it alone, so
pair it with Sound Gaming (runs in the browser) instead.

**CPU vs GPU**: each worker's device is `models.workers.<name>.device` in
`configs/app.yaml` (`cuda` on the Quadro RTX 5000, 16 GB; set `cpu` if the
GPU is unavailable); nothing else changes.

**Image model (game 3)**: `games.drawing.image_model` picks one entry of
`games.drawing.image_models`:
- `flux2_klein_4b` (default): FLUX.2 [klein] 4B, reads Italian directly, ~4 s
  per 768px image on the Quadro RTX 5000 (8.7 GB of GPU memory while loaded).
  `cuda_memory: stream_text_encoder` keeps the image model on the GPU and
  streams only the text encoder from system RAM.
- `z_image_turbo`: 6B, also reads Italian, ~40 s per image, ~13.7 GB peak
  (float16 with `cuda_fp16_guard`; Turing has no fast bfloat16).
- `sd_turbo`: small, runs on CPU, needs the description translated to English.

## Setup

```bash
conda activate ai-games          # cloned from the `chatterbox` env + web/model deps (requirements.txt)
cp .env.example .env             # set SECRET_KEY: python -c "import secrets; print(secrets.token_hex(32))"
flask --app "app:build" create-admin      # first admin
flask --app "app:build" seed-content      # default sounds / phrases / scenes (skips games that have content)
./start.sh
```

More accounts: `./add-user.sh <username>` (instructor) or
`./add-user.sh <username> admin`; it asks the password (min. 8 characters) and
works with the platform running or stopped. Existing accounts (password reset,
role, disable) are managed from **Amministrazione**.

Development server (accepts dotted overrides, e.g. `--server.port 8030`):
`python app.py`.

Model weights download from Hugging Face on first use into
`~/.cache/huggingface/` - run each game once before an event.

## Using it

- **Partite**: create a match (name, school, date, one team per line). The new
  match becomes the *current match*; every game page works on it. Teams of
  different matches are always separate, even with the same name.
- **Giochi** (dashboard): the four games + overall standings. Each game page
  has a turn timer, a "whose turn" picker, and a live per-game leaderboard
  with manual point correction.
- **Concludi gioco** (in each game's top bar): ends that game for the current
  match. Its points are locked (no new or manual points until **Riapri**), and
  a full-screen page shows the game's ranking with the placement points each
  team earns (10/8/6/4): teams start hidden, each *Rivela* shows one from
  last to first, *Mostra tutti* shows them all.
- **Proiettore**: full-screen live standings for a second screen. *Nascondi*
  hides the final ranking, then each *Rivela* reveals one team from last to
  first.
- **Archivia**: ends the match (read-only afterwards). Voice recordings,
  cloned clips and generated images of that match are deleted
  (`privacy.delete_media_on_archive`); names and scores remain.
- **Elimina definitivamente** (admins only; trash icon in the matches list or
  the button at the bottom of a match): removes a match, active or archived,
  with its teams, scores, recordings and images. Cannot be undone.
- **Amministrazione** (admins only): accounts (create, disable, reset
  password, role), game content, model processes.

### Scoring

Each game scores on its own scale. Per game, teams are ranked and receive
placement points (`scoring.placement_points`: 10/8/6/4, every place from 4th
down gets 4; ties share the placement), so the maximum over four games is 40. The final ranking sums placement points over the games that
were actually played; raw points break ties. Every point is a row in
`score_events`, so the match page shows a full log where any score can be undone.

## Audio quality

Recording is lossless and unprocessed: the browser captures raw PCM through an
AudioWorklet at the microphone's native rate (usually 48 kHz). Echo
cancellation, noise suppression and automatic gain are off, and the WAV is
32-bit float (`static/js/recorder.js`). Workers resample server-side with a
band-limited sinc resampler (`workers/audio_io.py`). The microphone requires
https (Cloudflare tunnel) or `http://localhost`.

## Code map

```
app.py                     app factory, CLI (create-user, create-admin, seed-content)
add-user.sh                add an account (wraps `flask create-user`)
deploy/conda-env.sh        conda activation shared by start.sh / add-user.sh
models.py                  users, matches/teams/score events, game content and state
services/model_manager.py  start/stop/health of model worker processes
services/scoring.py        leaderboards (per game + final)
services/context.py        current match (session), admin_required
services/media.py          per-match media folder (deleted on archive)
services/matches.py        permanent deletion of a match (rows + media)
routes/                    auth, home, matches, admin, models_api, games/<slug>.py
workers/                   one HTTP worker per model family (+ common.py, audio_io.py)
content/                   default game content (seed-content)
i18n/                      core.py + one module per game; it/en key parity checked at import
static/js/gamekit.js       shared game-page components (model badge, timer, team picker, mini board)
static/img/games/          game artwork (school-flyer pictures as WebP: <slug>.webp cards, <slug>-thumb.webp titles)
```

## Adding or changing game content

**Amministrazione > Contenuti giochi**: sounds to imitate (with the AudioSet
classes that count as a hit), voice phrases, drawing scenes (elements to
detect and forbidden words). Changes apply to the next turns.

## Cloudflare tunnel

```bash
sudo deploy/setup-local-tunnel.sh   # once, with ./start.sh running
```

It reads `deploy.tunnel`, `deploy.hostname` and `server.port` from
`configs/app.yaml`, adds `hostname -> http://127.0.0.1:<port>` to
`~/.cloudflared/config.yml` (the user's locally-managed tunnel; other apps can
add rules there too), installs and starts `cloudflared-<tunnel>.service`
(runs as the user, starts at boot), and points the DNS record at the tunnel
(`--overwrite-dns`). The machine's root `cloudflared.service` is a separate,
dashboard-managed tunnel and is left alone.

`deploy/enable-tunnel.sh` / `disable-tunnel.sh` are for the old workstation's
layout (a shared tunnel in `/etc/cloudflared/config.yml`); use
`disable-tunnel.sh` there to retire the old route. The tunnel is transport only:
every page except login requires an account. The microphone needs https, so
games 1, 2 and 4 work through the tunnel (or on http://localhost).
