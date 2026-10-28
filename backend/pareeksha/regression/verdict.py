"""When does a regression test pass? (FR-RG-2)

A test passes when its latest score is at least ``baseline - tolerance`` and the call had no
critical failure. The default tolerance is 5 points. A suite fails if any blocking test fails.
"""

from __future__ import annotations

DEFAULT_TOLERANCE = 5.0
DEFAULT_BASELINE = 80.0


def regression_passed(
    score: float | None, critical_failure: bool, baseline: float, tolerance: float
) -> bool:
    """``score >= baseline - tolerance`` and no critical failure; no score is a failure."""
    return score is not None and not critical_failure and score >= baseline - tolerance
