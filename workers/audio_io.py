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


def trim_leading_silence(waveform, sample_rate, frame_seconds=0.02, threshold_ratio=0.1, keep_seconds=0.15):
    """Drop the silence before the first spoken frame (keeping `keep_seconds`
    of it): a frame counts as speech when its RMS reaches `threshold_ratio`
    of the loudest frame's. Only cuts, never alters the audio."""
    frame = max(1, int(frame_seconds * sample_rate))
    frames = waveform[: waveform.numel() // frame * frame].reshape(-1, frame)
    if frames.numel() == 0:
        return waveform
    rms = frames.pow(2).mean(dim=1).sqrt()
    loud = torch.nonzero(rms >= rms.max() * threshold_ratio)
    if loud.numel() == 0:
        return waveform
    start = max(0, int(loud[0]) * frame - int(keep_seconds * sample_rate))
    return waveform[start:]
