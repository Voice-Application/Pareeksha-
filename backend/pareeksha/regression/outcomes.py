"""Read side of regression: each test's last result, and a regression run's items as outcomes."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.db.models import Calls, Evaluations, RegressionTests, RunItems, TestRuns
from pareeksha.db.queries import distinct_on
from pareeksha.evaluation.handlers import RunItemOutcome
from pareeksha.regression.verdict import regression_passed


@dataclass(frozen=True)
class LastResult:
    run_id: uuid.UUID
    score: float | None
    passed: bool


async def latest_results(
    session: AsyncSession, tests: Sequence[RegressionTests]
) -> dict[uuid.UUID, LastResult]:
    """The newest evaluated run item of every test, judged against the test's own thresholds."""
    if not tests:
        return {}
    stmt = (
        select(
            RunItems.regression_test_id,
            TestRuns.id,
            Evaluations.overall_score,
            Evaluations.critical_failure,
        )
        .join(TestRuns, TestRuns.id == RunItems.run_id)
        .join(Calls, Calls.run_item_id == RunItems.id)
        .join(Evaluations, Evaluations.call_id == Calls.id)
        .where(
            RunItems.regression_test_id.in_([t.id for t in tests]),
            RunItems.status == "evaluated",
            Evaluations.status == "ok",
        )
        .order_by(
            RunItems.regression_test_id,
            TestRuns.created_at.desc(),
            Evaluations.created_at.desc(),
        )
    )
    stmt = distinct_on(stmt, RunItems.regression_test_id)
    by_id = {t.id: t for t in tests}
    out: dict[uuid.UUID, LastResult] = {}
    for test_id, run_id, score, critical in (await session.execute(stmt)).all():
        if test_id is None:
            continue
        test = by_id[test_id]
        value = None if score is None else float(score)
        out[test_id] = LastResult(
            run_id,
            value,
            regression_passed(
                value, bool(critical), float(test.baseline_score), float(test.tolerance)
            ),
        )
    return out


async def run_outcomes(session: AsyncSession, run_id: uuid.UUID) -> list[RunItemOutcome]:
    """Every item of a run as the finalizer sees it, with the regression test's thresholds."""
    stmt = (
        select(
            RunItems.status,
            Evaluations.overall_score,
            Evaluations.passed,
            Evaluations.critical_failure,
            Evaluations.needs_human_review,
            RegressionTests.status,
            RegressionTests.baseline_score,
            RegressionTests.tolerance,
        )
        .select_from(RunItems)
        .outerjoin(Calls, Calls.run_item_id == RunItems.id)
        .outerjoin(Evaluations, (Evaluations.call_id == Calls.id) & (Evaluations.status == "ok"))
        .outerjoin(RegressionTests, RegressionTests.id == RunItems.regression_test_id)
        .where(RunItems.run_id == run_id)
        .order_by(RunItems.id, Evaluations.created_at.desc())
    )
    stmt = distinct_on(stmt, RunItems.id)
    outcomes: list[RunItemOutcome] = []
    for status, score, passed, critical, review, test_status, baseline, tolerance in (
        await session.execute(stmt)
    ).all():
        outcomes.append(
            RunItemOutcome(
                status=status,
                overall_score=None if score is None else float(score),
                passed=passed,
                critical_failure=bool(critical),
                needs_human_review=bool(review),
                blocking=test_status in (None, "blocking"),
                baseline_score=None if baseline is None else float(baseline),
                tolerance=None if tolerance is None else float(tolerance),
            )
        )
    return outcomes
