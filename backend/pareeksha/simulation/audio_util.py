"""Small PCM helpers for the caller pipeline."""

from __future__ import annotations

import io
import math
import wave

import numpy as np
from scipy.signal import resample_poly

from pareeksha.adapters.base import AUDIO_SAMPLE_RATE

FRAME_SAMPLES = AUDIO_SAMPLE_RATE * 20 // 1000


def wav_to_pcm16(wav: bytes, sample_rate: int = AUDIO_SAMPLE_RATE) -> bytes:
    """Decode a PCM WAV to mono s16le at ``sample_rate`` (first channel; resampled if needed)."""
    with wave.open(io.BytesIO(wav)) as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"expected 16-bit PCM WAV, got {8 * width}-bit")
    samples = np.frombuffer(raw, dtype="<i2")
    if channels > 1:
        samples = samples[::channels]
    if rate != sample_rate:
        divisor = math.gcd(rate, sample_rate)
        resampled = resample_poly(
            samples.astype(np.float32), sample_rate // divisor, rate // divisor
        )
        samples = np.clip(np.rint(resampled), -32768, 32767).astype("<i2")
    return samples.astype("<i2").tobytes()


def pcm_seconds(pcm: bytes, sample_rate: int = AUDIO_SAMPLE_RATE) -> float:
    return len(pcm) / 2 / sample_rate
