"""Procedurally synthesised background-noise beds (no network, no licensed clips).

Each category is a stateful, seeded generator. `NoiseSource.generate(n)` returns
unit-power noise (power calibrated once per category/rate on a fixed seed), and
the output is a pure function of (category, rate, seed, sequence of chunk sizes).
LineSimulator always draws fixed 20 ms frames, which makes its output independent of
how the caller chunks the input.
"""

from __future__ import annotations

from functools import cache

import numpy as np
from scipy import signal

CATEGORIES = (
    "office_babble",
    "street_traffic",
    "market_crowd",
    "bus_interior",
    "auto_rickshaw",
)

_CALIBRATION_SEED = 0xC0FFEE
_CALIBRATION_SECONDS = 30


class _Sos:
    """Stateful second-order-sections filter."""

    def __init__(self, sos: np.ndarray):
        self.sos = sos
        self.zi = np.zeros((sos.shape[0], 2))

    def __call__(self, x: np.ndarray) -> np.ndarray:
        y, self.zi = signal.sosfilt(self.sos, x, zi=self.zi)
        return y


def _lowpass(fc: float, rate: int, order: int = 2) -> _Sos:
    return _Sos(signal.butter(order, fc, btype="lowpass", fs=rate, output="sos"))


def _bandpass(lo: float, hi: float, rate: int, order: int = 2) -> _Sos:
    hi = min(hi, rate * 0.45)
    return _Sos(signal.butter(order, [lo, hi], btype="bandpass", fs=rate, output="sos"))


def _std_of_filtered_white(sos: np.ndarray, length: int) -> float:
    imp = np.zeros(length)
    imp[0] = 1.0
    h = signal.sosfilt(sos, imp)
    return float(np.sqrt(np.sum(h * h)))


class _Voice:
    """One babble talker: formant-filtered noise under a ~4 Hz syllabic envelope."""

    def __init__(self, rng: np.random.Generator, rate: int):
        f1 = rng.uniform(300, 800)
        f2 = rng.uniform(1000, 2400)
        self.formants = [
            _bandpass(f1 * 0.8, f1 * 1.25, rate),
            _bandpass(f2 * 0.8, f2 * 1.25, rate),
        ]
        self.env_filter = _lowpass(rng.uniform(2.5, 5.0), rate)
        self.env_std = _std_of_filtered_white(self.env_filter.sos, int(rate * 1.5))
        self.rng = rng

    def generate(self, n: int) -> np.ndarray:
        w = self.rng.standard_normal(n)
        body = self.formants[0](w) + 0.6 * self.formants[1](w)
        e = self.env_filter(self.rng.standard_normal(n)) / self.env_std
        env = 1.0 / (1.0 + np.exp(-2.0 * e))  # smooth 0..1 syllable bursts
        return body * env


class _Babble:
    def __init__(
        self, rng: np.random.Generator, rate: int, voices: int, crackle: float = 0.0
    ):
        self.voices = [_Voice(rng, rate) for _ in range(voices)]
        self.rng = rng
        self.crackle = crackle
        self.hiss = _bandpass(2000, 3600, rate)

    def generate(self, n: int) -> np.ndarray:
        out = np.zeros(n)
        for v in self.voices:
            out += v.generate(n)
        out /= np.sqrt(len(self.voices))
        if self.crackle:
            imp = (self.rng.random(n) < 0.004) * self.rng.standard_normal(n) * 4.0
            out += self.crackle * self.hiss(imp + 0.3 * self.rng.standard_normal(n))
        return out


class _Traffic:
    """Low rumble with slow swells (passing vehicles) and a little tyre hiss."""

    def __init__(self, rng: np.random.Generator, rate: int):
        self.rng = rng
        self.rumble = _lowpass(350, rate, order=3)
        self.hiss = _bandpass(800, 3000, rate)
        self.swell = _lowpass(0.4, rate)
        self.swell_std = _std_of_filtered_white(self.swell.sos, int(rate * 6))

    def generate(self, n: int) -> np.ndarray:
        s = self.swell(self.rng.standard_normal(n)) / self.swell_std
        swell = 1.0 + 0.25 * np.tanh(s)
        return (
            1.0 * self.rumble(self.rng.standard_normal(n))
            + 0.25 * self.hiss(self.rng.standard_normal(n))
        ) * swell


class _Harmonics:
    """Sum of harmonics of a slowly wobbling fundamental."""

    def __init__(
        self,
        rng: np.random.Generator,
        rate: int,
        f0: float,
        count: int,
        wobble: float,
        rolloff: float,
    ):
        self.rate = rate
        self.f0 = f0
        self.rolloff = rolloff
        self.count = min(count, int(rate * 0.45 / f0))
        self.phases = rng.uniform(0, 2 * np.pi, self.count)
        self.wobble_filter = _lowpass(1.5, rate)
        self.wobble_std = _std_of_filtered_white(self.wobble_filter.sos, int(rate * 4))
        self.wobble = wobble
        self.rng = rng
        self.phase = 0.0  # fundamental phase accumulator (radians)

    def generate(self, n: int) -> np.ndarray:
        w = self.wobble_filter(self.rng.standard_normal(n)) / self.wobble_std
        inst_f = self.f0 * (1.0 + self.wobble * w)
        ph = self.phase + np.cumsum(2 * np.pi * inst_f / self.rate)
        self.phase = float(ph[-1] % (2 * np.pi))
        out = np.zeros(n)
        for k in range(1, self.count + 1):
            out += np.sin(k * ph + self.phases[k - 1]) / k**self.rolloff
        return out


class _Bus:
    def __init__(self, rng: np.random.Generator, rate: int):
        self.rng = rng
        self.engine = _Harmonics(rng, rate, 32.0, 14, 0.05, 0.6)
        self.rumble = _lowpass(250, rate, order=3)
        self.rattle = _bandpass(900, 2600, rate)

    def generate(self, n: int) -> np.ndarray:
        hits = (self.rng.random(n) < 0.002) * self.rng.standard_normal(n) * 3.0
        return (
            0.8 * self.engine.generate(n)
            + 1.0 * self.rumble(self.rng.standard_normal(n))
            + 0.5 * self.rattle(hits)
        )


class _Rickshaw:
    """Two-stroke put-put: strongly amplitude-modulated harmonic buzz plus wideband rasp."""

    def __init__(self, rng: np.random.Generator, rate: int):
        self.rng = rng
        self.engine = _Harmonics(rng, rate, 38.0, 30, 0.08, 0.35)
        self.rasp = _bandpass(250, 3200, rate)
        self.am = _Harmonics(rng, rate, 19.0, 1, 0.08, 0.0)

    def generate(self, n: int) -> np.ndarray:
        am = 0.65 + 0.35 * self.am.generate(n)
        return (
            self.engine.generate(n) + 0.7 * self.rasp(self.rng.standard_normal(n))
        ) * am


def _build(category: str, rng: np.random.Generator, rate: int):
    if category == "office_babble":
        return _Babble(rng, rate, voices=6)
    if category == "market_crowd":
        return _Babble(rng, rate, voices=16, crackle=0.5)
    if category == "street_traffic":
        return _Traffic(rng, rate)
    if category == "bus_interior":
        return _Bus(rng, rate)
    if category == "auto_rickshaw":
        return _Rickshaw(rng, rate)
    raise ValueError(
        f"unknown noise category: {category!r} (expected one of {CATEGORIES})"
    )


@cache
def _calibrated_power(category: str, rate: int) -> float:
    gen = _build(category, np.random.default_rng(_CALIBRATION_SEED), rate)
    x = gen.generate(rate * _CALIBRATION_SECONDS)
    return float(np.mean(x * x))


class NoiseSource:
    """Seeded, unit-power background noise."""

    def __init__(self, category: str, rate: int, seed: int):
        self.category = category
        self.rate = rate
        self._scale = 1.0 / np.sqrt(_calibrated_power(category, rate))
        self._gen = _build(category, np.random.default_rng(seed), rate)

    def generate(self, n: int) -> np.ndarray:
        return (self._gen.generate(n) * self._scale).astype(np.float32)
