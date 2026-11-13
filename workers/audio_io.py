"""Audio loading for the workers.

Browser recordings arrive as lossless 32-bit float WAV at the microphone's
native rate (static/js/recorder.js). Models need specific rates, so the
resampling happens here, with torchaudio's band-limited sinc resampler
(Kaiser window) rather than the browser's - quality is a requirement.
"""

import io

import soundfile as sf
import torch
import torchaudio.functional as AF


def load_wav_bytes(data):
    """Returns (mono float32 tensor [samples], sample_rate) from WAV bytes."""
    audio, sample_rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    waveform = torch.from_numpy(audio.T).mean(dim=0)
    return waveform, sample_rate


def resample(waveform, from_rate, to_rate):
    if from_rate == to_rate:
        return waveform
    return AF.resample(
        waveform, from_rate, to_rate,
        lowpass_filter_width=64, rolloff=0.9475937167399596,
        resampling_method="sinc_interp_kaiser", beta=14.769656459379492,
    )


def load_wav_bytes_at(data, target_rate):
    waveform, sample_rate = load_wav_bytes(data)
    return resample(waveform, sample_rate, target_rate)
