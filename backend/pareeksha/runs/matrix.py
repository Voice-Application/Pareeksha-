"""Matrix expansion (TRD section 3, planner): scenario x persona x noise profile x repeats.

Pure functions, no I/O. The per-item seed is derived from the run seed and the cell, never from
the position in a list, so a re-plan (a redelivered ``run.requested``) produces the same rows and
the unique key ``(run, scenario, persona, noise profile, seed)`` makes the insert idempotent.
"""

from __future__ import annotations

import hashlib
import itertools
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

#: Upper bound of one run's matrix. Every item is a real call (TTS + STT + LLM), so a typo in a
#: wizard (20 x 20 x 20 x 20) must fail fast instead of queueing 160 000 calls.
MAX_RUN_ITEMS = 1000

_BIGINT_MAX = 2**63 - 1


@dataclass(frozen=True, slots=True)
class Cell:
    """One call to make."""

    scenario_id: uuid.UUID
    persona_id: uuid.UUID
    noise_profile_id: uuid.UUID
    seed: int
    regression_test_id: uuid.UUID | None = None


def unique_in_order(ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """Drop repeated ids, keeping the first occurrence (a repeated id would repeat a cell)."""
    return list(dict.fromkeys(ids))


def item_count(scenarios: int, personas: int, profiles: int, repeats: int) -> int:
    return scenarios * personas * profiles * repeats


def item_seed(
    run_seed: int,
    scenario_id: uuid.UUID,
    persona_id: uuid.UUID,
    noise_profile_id: uuid.UUID,
    repeat: int,
    salt: str = "",
) -> int:
    """Deterministic non-negative 63-bit seed (``run_items.seed`` is a bigint).

    ``salt`` keeps two cells that are otherwise identical apart (two regression tests that share
    a scenario, persona and noise profile each get their own call).
    """
    material = f"{run_seed}:{scenario_id}:{persona_id}:{noise_profile_id}:{repeat}:{salt}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") & _BIGINT_MAX


def expand_matrix(
    *,
    run_seed: int,
    scenario_ids: Iterable[uuid.UUID],
    persona_ids: Iterable[uuid.UUID],
    noise_profile_ids: Iterable[uuid.UUID],
    repeats: int,
) -> Iterator[Cell]:
    """Every (scenario, persona, noise profile, repeat) combination, in a stable order."""
    for scenario, persona, profile in itertools.product(
        unique_in_order(scenario_ids),
        unique_in_order(persona_ids),
        unique_in_order(noise_profile_ids),
    ):
        for repeat in range(repeats):
            seed = item_seed(run_seed, scenario, persona, profile, repeat)
            yield Cell(scenario, persona, profile, seed)
