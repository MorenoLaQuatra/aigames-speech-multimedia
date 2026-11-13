"""Voice cloning worker (game 2, "voices"): Chatterbox Multilingual.

Started on demand by services/model_manager.py - never by hand in normal
use. For a standalone test:
    AI_GAMES_WORKER=voice_clone AI_GAMES_CONFIG_PATH=configs/app.yaml python workers/voice_clone.py

    GET  /health -> 200 once the model is loaded (see workers/common.py)
    POST /clone  -> multipart: file `reference_audio` (WAV, any rate/format
                    soundfile reads - the browser sends float32 at the mic's
                    native rate), fields `text`, `language` ("it"/"en"/...),
                    `exaggeration` (0-1). Response: raw WAV bytes (16-bit PCM,
                    model.sr = 24 kHz), Content-Type audio/wav. Errors: JSON.
"""

import io
import os
import tempfile
import time

from common import create_worker_app, json_error, load_worker_config, resolve_device, serve  # noqa: I001

config, worker_cfg, NAME = load_worker_config()

# On CPU, hide the GPU entirely so nothing (not even CUDA context init in a
# library) touches it - it may be busy with someone else's training.
if worker_cfg.device == "cpu":
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

import logging  # noqa: E402

import soundfile as sf  # noqa: E402
from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: E402
from flask import Response, request  # noqa: E402

from audio_io import load_wav_bytes_at  # noqa: E402

log = logging.getLogger(NAME)

# Chatterbox's S3Gen works at 24 kHz; it would resample a reference itself
# with librosa, but we do it with the band-limited sinc resampler instead
# (workers/audio_io.py) so the prompt is as clean as possible.
REFERENCE_RATE = 24000
MAX_TEXT_LENGTH = 300

device = resolve_device(worker_cfg.device)

started = time.time()
# Chatterbox compares `device` against the *string* "cpu" to decide whether
# to map its CUDA-saved checkpoints to CPU, so pass str(device), not the
# torch.device object (that silently skips the mapping and crashes on load).
model = ChatterboxMultilingualTTS.from_pretrained(device=str(device), t3_model=config.games.voices.t3_model)
model.generate("Pronto.", language_id="it")  # warm-up with the built-in voice
log.info("Chatterbox loaded on %s in %.1fs", device, time.time() - started)

app = create_worker_app(NAME)


@app.route("/clone", methods=["POST"])
def clone():
    text = request.form.get("text", "").strip()
    if not text or len(text) > MAX_TEXT_LENGTH:
        return json_error("text is empty or too long", 400)
    language = request.form.get("language", "").strip()
    if not language:
        return json_error("language is required", 400)
    try:
        exaggeration = float(request.form["exaggeration"])
    except (KeyError, ValueError):
        return json_error("exaggeration must be a number", 400)
    reference = request.files.get("reference_audio")
    if reference is None:
        return json_error("reference_audio file is required", 400)

    waveform = load_wav_bytes_at(reference.read(), REFERENCE_RATE)
    if waveform.numel() < REFERENCE_RATE:
        return json_error("reference audio is shorter than 1 second", 400)

    t0 = time.time()
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        sf.write(tmp.name, waveform.numpy(), REFERENCE_RATE, subtype="FLOAT")
        wav = model.generate(text, language_id=language, audio_prompt_path=tmp.name, exaggeration=exaggeration)
    log.info("Cloned %d chars in %.1fs", len(text), time.time() - t0)

    buffer = io.BytesIO()
    sf.write(buffer, wav.squeeze(0).cpu().numpy(), model.sr, format="WAV", subtype="PCM_16")
    return Response(buffer.getvalue(), mimetype="audio/wav")


if __name__ == "__main__":
    serve(app, worker_cfg)
