"""Stateless and stateful DSP primitives for the line simulator (no network).

All internal audio is mono float32 in [-1, 1]. The pipeline rate is 16 kHz.
"""

from __future__ import annotations

import audioop  # stdlib <= 3.12; audioop-lts on >= 3.13 (see requirements.txt)

import numpy as np
from scipy import signal

PIPELINE_RATE = 16_000
FRAME_MS = 20
ACTIVE_THRESHOLD_DBFS = -45.0
"""A 20 ms frame is speech-active when its RMS exceeds this level (dBFS)."""

NOMINAL_SPEECH_POWER = 10 ** (-26.0 / 10.0)
"""Power assumed for speech until real speech has been observed (streaming only)."""


def frame_len(rate: int) -> int:
    return rate * FRAME_MS // 1000


def pcm16_to_float(data: bytes) -> np.ndarray:
    return (np.frombuffer(data, dtype="<i2").astype(np.float32)) / 32768.0


def float_to_pcm16(x: np.ndarray) -> bytes:
    y = np.clip(np.asarray(x, dtype=np.float64), -1.0, 1.0) * 32767.0
    return np.rint(y).astype("<i2").tobytes()


def power(x: np.ndarray) -> float:
    return float(np.mean(np.square(x, dtype=np.float64))) if len(x) else 0.0


def active_mask(x: np.ndarray, rate: int) -> np.ndarray:
    """Per-sample boolean mask of speech-active 20 ms frames (frames start at sample 0)."""
    n = len(x)
    mask = np.zeros(n, dtype=bool)
    flen = frame_len(rate)
    thr = 10 ** (ACTIVE_THRESHOLD_DBFS / 10.0)
    for start in range(0, n, flen):
        if power(x[start : start + flen]) > thr:
            mask[start : start + flen] = True
    return mask


def active_power(x: np.ndarray, rate: int) -> float:
    """Mean power over speech-active samples only (0.0 when there are none)."""
    mask = active_mask(x, rate)
    return power(x[mask]) if mask.any() else 0.0


def noise_gain(speech_power: float, noise_power: float, snr_db: float) -> float:
    """Gain g such that 10*log10(Ps / (g^2 * Pn)) == snr_db."""
    return float(np.sqrt(speech_power / (noise_power * 10 ** (snr_db / 10.0))))


def measure_snr_db(speech: np.ndarray, noise: np.ndarray, rate: int) -> float:
    """SNR in dB with both powers measured on the speech-active samples of `speech`."""
    mask = active_mask(speech, rate)
    return 10.0 * np.log10(power(speech[mask]) / power(noise[mask]))


def mix_at_snr(
    speech: np.ndarray, noise: np.ndarray, snr_db: float, rate: int
) -> np.ndarray:
    """Offline mix at an exact SNR (noise tiled/trimmed to the speech length)."""
    reps = int(np.ceil(len(speech) / max(len(noise), 1)))
    nz = np.tile(noise, reps)[: len(speech)]
    mask = active_mask(speech, rate)
    g = noise_gain(power(speech[mask]), power(nz[mask]), snr_db)
    return (speech + g * nz).astype(np.float32)


def codec_roundtrip(x: np.ndarray, codec: str) -> np.ndarray:
    """G.711 round trip. 'alaw' (Indian PSTN) or 'mulaw'; 'none' is identity."""
    if codec == "none":
        return x
    pcm = float_to_pcm16(x)
    if codec == "alaw":
        out = audioop.alaw2lin(audioop.lin2alaw(pcm, 2), 2)
    elif codec == "mulaw":
        out = audioop.ulaw2lin(audioop.lin2ulaw(pcm, 2), 2)
    else:
        raise ValueError(f"unknown codec: {codec}")
    return pcm16_to_float(out)


def hard_clip(x: np.ndarray, drive: float, ceiling: float) -> np.ndarray:
    return np.clip(x * drive, -ceiling, ceiling).astype(np.float32)


class StreamingBandpass:
    """Stateful Butterworth band-pass (PSTN 300-3400 Hz)."""

    def __init__(
        self, rate: int, low: float = 300.0, high: float = 3400.0, order: int = 4
    ):
        self._sos = signal.butter(
            order, [low, high], btype="bandpass", fs=rate, output="sos"
        )
        self._zi = np.zeros((self._sos.shape[0], 2))

    def process(self, x: np.ndarray) -> np.ndarray:
        y, self._zi = signal.sosfilt(self._sos, x.astype(np.float64), zi=self._zi)
        return y.astype(np.float32)


class StreamingResampler:
    """Stateful x2 down/up resampler (16 kHz <-> 8 kHz) using a linear-phase FIR.

    Group delay is FIR_DELAY samples at 16 kHz per instance; the caller compensates.
    """

    NUMTAPS = 65
    FIR_DELAY = (NUMTAPS - 1) // 2
    _H = signal.firwin(NUMTAPS, 3800.0, fs=PIPELINE_RATE)

    def __init__(self, mode: str):
        if mode not in ("down", "up"):
            raise ValueError(mode)
        self.mode = mode
        self._zi = np.zeros(self.NUMTAPS - 1)
        self._seen = 0  # input samples consumed (down mode decimation phase)

    def process(self, x: np.ndarray) -> np.ndarray:
        x = x.astype(np.float64)
        if self.mode == "down":
            y, self._zi = signal.lfilter(self._H, 1.0, x, zi=self._zi)
            offset = (-self._seen) % 2
            self._seen += len(x)
            return y[offset::2].astype(np.float32)
        z = np.zeros(2 * len(x))
        z[::2] = 2.0 * x
        y, self._zi = signal.lfilter(self._H, 1.0, z, zi=self._zi)
        return y.astype(np.float32)
