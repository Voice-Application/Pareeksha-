"""Audio helpers for ``POST /noise-profiles/{id}/preview``: decode an uploaded clip, make the
built-in sample, run it through a ``LineProfile`` and encode the result as WAV.

The built-in sample is synthetic (voiced bursts through formant filters, no real voice): it is
there so the degradation can be heard without a recording or a TTS call.
"""

from __future__ import annotations

import io
import math
import wave

import numpy as np
from scipy import signal

from pareeksha.audio.line_simulator import LineSimulator
from pareeksha.audio.profiles import LineProfile

RATE = 16000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CLIP_SECONDS = 60.0


class UnsupportedAudioError(ValueError):
    """The upload is not a WAV file Pareeksha can read (maps to 422 ``unsupported_audio``)."""


def decode_wav(data: bytes) -> np.ndarray:
    """16-bit PCM WAV bytes -> mono float32 at 16 kHz."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            channels, width, rate, frames = (
                w.getnchannels(),
                w.getsampwidth(),
                w.getframerate(),
                w.getnframes(),
            )
            if width != 2:
                raise UnsupportedAudioError("only 16-bit PCM WAV is supported")
            if frames == 0 or rate <= 0:
                raise UnsupportedAudioError("the WAV file contains no audio")
            if frames / rate > MAX_CLIP_SECONDS:
                raise UnsupportedAudioError(f"clip is longer than {MAX_CLIP_SECONDS:.0f} s")
            raw = w.readframes(frames)
    except (wave.Error, EOFError) as exc:
        raise UnsupportedAudioError(f"not a readable WAV file: {exc}") from exc
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples[: len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
    if rate != RATE:
        g = math.gcd(rate, RATE)
        samples = signal.resample_poly(samples, RATE // g, rate // g).astype(np.float32)
    return samples.astype(np.float32)


def encode_wav(audio: np.ndarray, rate: int = RATE) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def builtin_sample(seconds: float = 6.0, seed: int = 1, peak_rms: float = 0.08) -> np.ndarray:
    """Speech-like bursts separated by digital silence, so speech-active SNR is meaningful."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    out = np.zeros(n)
    pos = int(0.2 * RATE)
    while pos < n:
        seg_n = min(int(rng.uniform(0.25, 0.7) * RATE), n - pos)
        t = np.arange(seg_n) / RATE
        f0 = rng.uniform(100, 220) * (1 + 0.03 * np.sin(2 * np.pi * 5 * t))
        phase = 2 * np.pi * np.cumsum(f0) / RATE
        src = sum(np.sin(k * phase) / k for k in range(1, 30))
        f1, f2 = rng.uniform(400, 800), rng.uniform(1100, 2400)
        sos1 = signal.butter(2, [f1 * 0.85, f1 * 1.2], "bandpass", fs=RATE, output="sos")
        sos2 = signal.butter(2, [f2 * 0.85, f2 * 1.2], "bandpass", fs=RATE, output="sos")
        seg = signal.sosfilt(sos1, src) + 0.5 * signal.sosfilt(sos2, src)
        fade = min(160, seg_n // 2)
        env = np.ones(seg_n)
        env[:fade] = np.linspace(0, 1, fade)
        env[seg_n - fade :] = np.linspace(1, 0, fade)
        out[pos : pos + seg_n] = seg * env
        pos += seg_n + int(rng.uniform(0.15, 0.4) * RATE)
    rms = float(np.sqrt(np.mean(out[np.abs(out) > 0] ** 2))) or 1.0
    return (out * (peak_rms / rms)).astype(np.float32)


def degrade(profile: LineProfile, audio: np.ndarray, seed: int = 0) -> np.ndarray:
    """The clip as it would arrive over the profile's line (16 kHz in, 16 kHz out)."""
    return np.asarray(LineSimulator.simulate(profile, audio, seed), dtype=np.float32)
