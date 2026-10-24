"""Synthetic, license-free speech-like fixtures (no real voices, no network)."""

from __future__ import annotations

import itertools

import numpy as np
from scipy import signal

RATE = 16000


def synth_speech(seconds: float = 10.0, seed: int = 1, peak_rms: float = 0.08) -> np.ndarray:
    """Voiced-looking bursts (glottal pulse train through formants, vibrato f0)
    separated by true digital silence, so speech-active masking is meaningful."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    out = np.zeros(n)
    pos = int(0.2 * RATE)
    while pos < n:
        dur = int(rng.uniform(0.25, 0.7) * RATE)
        seg_n = min(dur, n - pos)
        t = np.arange(seg_n) / RATE
        f0 = rng.uniform(100, 220) * (1 + 0.03 * np.sin(2 * np.pi * 5 * t))
        phase = 2 * np.pi * np.cumsum(f0) / RATE
        src = sum(np.sin(k * phase) / k for k in range(1, 30))
        f1, f2 = rng.uniform(400, 800), rng.uniform(1100, 2400)
        sos1 = signal.butter(2, [f1 * 0.85, f1 * 1.2], "bandpass", fs=RATE, output="sos")
        sos2 = signal.butter(2, [f2 * 0.85, f2 * 1.2], "bandpass", fs=RATE, output="sos")
        seg = signal.sosfilt(sos1, src) + 0.5 * signal.sosfilt(sos2, src)
        env = np.hanning(seg_n) ** 0.5
        seg = seg * env
        seg *= peak_rms / (np.sqrt(np.mean(seg**2)) + 1e-12)
        out[pos : pos + seg_n] = seg
        pos += seg_n + int(rng.uniform(0.15, 0.5) * RATE)
    return out.astype(np.float32)


def spectrum_db(x: np.ndarray, bands: int = 24, rate: int = RATE) -> np.ndarray:
    """Coarse log-band energy profile (dB) for distinctness checks."""
    f, p = signal.welch(x, fs=rate, nperseg=1024)
    edges = np.linspace(0, rate / 2, bands + 1)
    return np.array(
        [
            10 * np.log10(p[(f >= lo) & (f < hi)].mean() + 1e-20)
            for lo, hi in itertools.pairwise(edges)
        ]
    )
