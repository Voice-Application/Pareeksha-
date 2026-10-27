"""Speaker-grouped bootstrap confidence intervals (FR-DI-4).

Clips from one speaker are not independent (voice, accent, microphone), so the resampling unit is
the speaker: draw speakers with replacement, pool all of their clips, recompute the pooled ratio
(total word errors / total reference words). With few speakers the interval is honestly wide; with
one speaker it collapses to the point estimate and the report says so.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import numpy as np

DEFAULT_RESAMPLES = 2000
DEFAULT_SEED = 20261024


def pooled_ratio(numerators: Iterable[float], denominators: Iterable[float]) -> float:
    num, den = sum(numerators), sum(denominators)
    return num / den if den else 0.0


def speaker_bootstrap_ci(
    items: Iterable[tuple[str, float, float]],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """95 % percentile interval of ``sum(num) / sum(den)`` resampling whole speakers.

    ``items`` are ``(speaker_id, numerator, denominator)`` per clip. Deterministic for a seed.
    """
    per_speaker: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for speaker, num, den in items:
        per_speaker[speaker][0] += num
        per_speaker[speaker][1] += den
    if not per_speaker:
        return (0.0, 0.0)
    nums = np.array([v[0] for v in per_speaker.values()])
    dens = np.array([v[1] for v in per_speaker.values()])
    point = pooled_ratio(nums, dens)
    if len(per_speaker) < 2:
        return (point, point)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(nums), size=(resamples, len(nums)))
    sample_num, sample_den = nums[idx].sum(axis=1), dens[idx].sum(axis=1)
    ratios = np.divide(sample_num, sample_den, out=np.zeros(resamples), where=sample_den > 0)
    alpha = (1.0 - confidence) / 2.0
    lo, hi = np.quantile(ratios, [alpha, 1.0 - alpha])
    return (float(lo), float(hi))
