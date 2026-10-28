"""Run compare (``GET /runs/compare``, FR-RG-3): per-cell score deltas between two runs.

A cell is ``(scenario title, persona name, noise profile name)``. A cell run several times
(``repeats``) is the mean of its evaluated items and counts as passed only when all of them
passed. ``delta = head - base`` (null when either side has no evaluated item), ``newly_failing``
means the cell passed in ``base`` and does not in ``head``. The summary counts cells present and
scored in both runs: ``regressed`` (delta < 0), ``improved`` (delta > 0), ``unchanged``.
Cells are ordered worst delta first, then cells without a delta, by name.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.errors import ApiError
from pareeksha.calls.service import latest_evaluations
from pareeksha.db.models import Calls, NoiseProfiles, Personas, RunItems, Scenarios, TestRuns
from pareeksha.schemas.runs import RunCompareCell, RunCompareOut, RunCompareSummary

Cell = tuple[str, str, str]


@dataclass
class CellResult:
    scores: list[float] = field(default_factory=list)
    passed: list[bool] = field(default_factory=list)

    @property
    def score(self) -> float | None:
        return round(sum(self.scores) / len(self.scores), 2) if self.scores else None

    @property
    def all_passed(self) -> bool | None:
        return all(self.passed) if self.passed else None


async def cell_results(session: AsyncSession, run_id: uuid.UUID) -> dict[Cell, CellResult]:
    ev = latest_evaluations()
    rows = await session.execute(
        select(Scenarios.title, Personas.name, NoiseProfiles.name, ev.c.overall_score, ev.c.passed)
        .select_from(RunItems)
        .join(Scenarios, Scenarios.id == RunItems.scenario_id)
        .join(Personas, Personas.id == RunItems.persona_id)
        .join(NoiseProfiles, NoiseProfiles.id == RunItems.noise_profile_id)
        .outerjoin(Calls, Calls.run_item_id == RunItems.id)
        .outerjoin(ev, ev.c.call_id == Calls.id)
        .where(RunItems.run_id == run_id)
    )
    cells: dict[Cell, CellResult] = defaultdict(CellResult)
    for scenario, persona, profile, score, passed in rows.all():
        result = cells[(scenario, persona, profile)]
        if score is not None:
            result.scores.append(float(score))
        if passed is not None:
            result.passed.append(passed)
    return cells


def compare_cells(base: dict[Cell, CellResult], head: dict[Cell, CellResult]) -> RunCompareOut:
    out: list[RunCompareCell] = []
    regressed = improved = unchanged = 0
    for key in sorted(base.keys() | head.keys()):
        b, h = base.get(key), head.get(key)
        base_score = None if b is None else b.score
        head_score = None if h is None else h.score
        delta = None
        if base_score is not None and head_score is not None:
            delta = round(head_score - base_score, 2)
            if delta < 0:
                regressed += 1
            elif delta > 0:
                improved += 1
            else:
                unchanged += 1
        out.append(
            RunCompareCell(
                scenario=key[0],
                persona=key[1],
                profile=key[2],
                base_score=base_score,
                head_score=head_score,
                delta=delta,
                newly_failing=(
                    b is not None
                    and h is not None
                    and b.all_passed is True
                    and h.all_passed is False
                ),
            )
        )
    out.sort(key=lambda c: (c.delta is None, c.delta if c.delta is not None else 0.0))
    return RunCompareOut(
        cells=out,
        summary=RunCompareSummary(regressed=regressed, improved=improved, unchanged=unchanged),
    )


async def compare_runs(
    session: AsyncSession, project_id: uuid.UUID, base: uuid.UUID, head: uuid.UUID
) -> RunCompareOut:
    found = set(
        (
            await session.scalars(
                select(TestRuns.id).where(
                    TestRuns.id.in_([base, head]), TestRuns.project_id == project_id
                )
            )
        ).all()
    )
    missing = [str(i) for i in (base, head) if i not in found]
    if missing:
        raise ApiError(404, "not_found", "Run not found", {"ids": missing})
    return compare_cells(await cell_results(session, base), await cell_results(session, head))
