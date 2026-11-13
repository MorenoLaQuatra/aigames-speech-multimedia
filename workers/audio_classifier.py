"""Model worker: AudioSet sound classifier (game 1, "noise").

Started on demand by services/model_manager.py - never by hand. Loads an
Audio Spectrogram Transformer fine-tuned on AudioSet (527 classes,
config.games.noise.model_id), then serves:

  GET  /health    -> 200 once the model is loaded
  POST /classify  -> multipart file "audio" (WAV, any rate, float or int PCM)
                     200 {"predictions": [{"label", "score"}, ... top 20],
                          "duration": seconds, "rms": float}
                     400 {"error": ...} for missing / unreadable / too short audio

Scores are sigmoids, not a softmax: AudioSet is multi-label, so each class
gets an independent probability.
"""

import logging

import soundfile as sf
import torch
from flask import request
from transformers import ASTFeatureExtractor, ASTForAudioClassification

from common import create_worker_app, json_error, load_worker_config, resolve_device, serve
from audio_io import load_wav_bytes, resample

TOP_N = 20
MIN_SECONDS = 0.3

config, worker_cfg, worker_name = load_worker_config()
log = logging.getLogger(worker_name)

device = resolve_device(worker_cfg.device)
model_id = config.games.noise.model_id
log.info("Loading %s on %s", model_id, device)
extractor = ASTFeatureExtractor.from_pretrained(model_id)
model = ASTForAudioClassification.from_pretrained(model_id).to(device).eval()
labels = [model.config.id2label[i] for i in range(model.config.num_labels)]
sample_rate = extractor.sampling_rate


def classify(waveform):
    inputs = extractor(waveform.numpy(), sampling_rate=sample_rate, return_tensors="pt").to(device)
    with torch.inference_mode():
        logits = model(**inputs).logits[0]
    scores = torch.sigmoid(logits).cpu()
    top = torch.topk(scores, TOP_N)
    return [{"label": labels[i], "score": round(float(s), 4)} for s, i in zip(top.values, top.indices)]


# Warm-up so the first real request isn't slower than the rest.
classify(torch.zeros(sample_rate))
log.info("Ready")

app = create_worker_app(worker_name)


@app.route("/classify", methods=["POST"])
def classify_route():
    upload = request.files.get("audio")
    if upload is None:
        return json_error("No 'audio' file in the request.", 400)
    data = upload.read()
    if not data:
        return json_error("Empty audio file.", 400)
    try:
        waveform, rate = load_wav_bytes(data)
    except sf.LibsndfileError as exc:
        return json_error(f"Unreadable audio: {exc}", 400)
    duration = waveform.shape[0] / rate
    if duration < MIN_SECONDS:
        return json_error(f"Audio too short ({duration:.2f}s, minimum {MIN_SECONDS}s).", 400)
    waveform = resample(waveform, rate, sample_rate)
    rms = float(torch.sqrt(torch.mean(waveform ** 2)))
    return {"predictions": classify(waveform), "duration": round(duration, 3), "rms": round(rms, 5)}


if __name__ == "__main__":
    serve(app, worker_cfg)
