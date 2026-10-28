"""Seeded barge-in plan (FR-RN-6, TRD section 5 ``BargeInScheduler``).

Interrupting personas start speaking 0.8-2.5 s into an agent turn. Whether a given agent turn is
interrupted is a seeded coin flip with probability 0 / .25 / .5 / .8 for interruption levels 0-3.
Both choices depend only on ``(seed, agent turn number)``, so a call replays identically.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

#: Probability that an agent turn is interrupted, by persona ``interruption_level``.
LEVEL_PROBABILITY: tuple[float, float, float, float] = (0.0, 0.25, 0.5, 0.8)


@dataclass(frozen=True)
class BargeInPlan:
    #: Seconds after the agent's speech started at which the caller starts talking.
    offset_s: float


class BargeInScheduler:
    def __init__(
        self,
        interruption_level: int,
        seed: int,
        *,
        min_s: float = 0.8,
        max_s: float = 2.5,
    ) -> None:
        if not 0 <= interruption_level < len(LEVEL_PROBABILITY):
            raise ValueError("interruption_level must be 0..3")
        if not 0 < min_s <= max_s:
            raise ValueError("need 0 < min_s <= max_s")
        self.probability = LEVEL_PROBABILITY[interruption_level]
        self._seed = seed
        self._min = min_s
        self._max = max_s

    def plan(self, agent_turn_number: int) -> BargeInPlan | None:
        """Plan for the 0-based ``agent_turn_number``-th agent turn; None = do not interrupt."""
        if self.probability <= 0:
            return None
        rng = random.Random(f"barge-in:{self._seed}:{agent_turn_number}")
        if rng.random() >= self.probability:
            return None
        return BargeInPlan(offset_s=round(rng.uniform(self._min, self._max), 3))
