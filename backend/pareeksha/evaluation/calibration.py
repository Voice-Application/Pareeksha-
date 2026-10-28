"""Judge vs human agreement (FR-EV-8): Cohen's kappa on pass/fail, Spearman on the overall score,
mean absolute error per rubric dimension. Pure functions; the endpoint feeds them from the DB."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LabelPair:
    """One judged call that a human also reviewed."""

    judge_passed: bool
    human_passed: bool
    judge_score: float | None = None
    human_score: float | None = None
    judge_dimensions: Mapping[str, int] = field(default_factory=dict)
    human_dimensions: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Calibration:
    n: int
    kappa_pass_fail: float | None
    spearman_overall: float | None
    dimension_mae: dict[str, float]


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    """(observed - chance) / (1 - chance) for two binary raters; ``None`` when undefined (no
    labels, or both raters constant so chance agreement is 1)."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    chance = sum((sum(x == v for x in a) / n) * (sum(y == v for y in b) / n) for v in (True, False))
    if chance == 1.0:
        return None
    return (observed - chance) / (1.0 - chance)


def _ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks; ties share the average of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Pearson correlation of the ranks; ``None`` for fewer than 2 points or a constant series."""
    if len(x) != len(y) or len(x) < 2:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def compute_calibration(pairs: Sequence[LabelPair]) -> Calibration:
    judge_scores: list[float] = []
    human_scores: list[float] = []
    errors: dict[str, list[int]] = defaultdict(list)
    for p in pairs:
        if p.judge_score is not None and p.human_score is not None:
            judge_scores.append(float(p.judge_score))
            human_scores.append(float(p.human_score))
        for dimension, human in p.human_dimensions.items():
            if dimension in p.judge_dimensions:
                errors[dimension].append(abs(p.judge_dimensions[dimension] - human))
    kappa = cohen_kappa([p.judge_passed for p in pairs], [p.human_passed for p in pairs])
    rho = spearman(judge_scores, human_scores)
    return Calibration(
        n=len(pairs),
        kappa_pass_fail=None if kappa is None else round(kappa, 4),
        spearman_overall=None if rho is None else round(rho, 4),
        dimension_mae={d: round(sum(e) / len(e), 4) for d, e in sorted(errors.items())},
    )
