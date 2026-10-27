"""Regression runs and tests (docs/06-api-spec.md sections 3 and 12). Promotion: ``calls.py``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.auth import ReadKey, WriteKey
from pareeksha.api.crud import flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.outbox import enqueue_event
from pareeksha.db.models import Agents, RegressionTests, RubricVersions, Scenarios, TestRuns
from pareeksha.events.schemas import RunRequested, make_envelope
from pareeksha.regression.estimate import estimate_run, remaining_budget
from pareeksha.regression.outcomes import latest_results
from pareeksha.schemas.common import Page
from pareeksha.schemas.regression import RegressionTestOut, RegressionTestUpdate
from pareeksha.schemas.runs import RegressionRunCreate, RegressionStatus, RunCreated

router = APIRouter(tags=["regression"], responses=AUTH_ERRORS)

_SNAPSHOT_FIELDS = (
    "name",
    "description",
    "adapter",
    "endpoint_url",
    "adapter_config",
    "languages",
    "glass_box",
    "mandatory_disclosures",
    "forbidden_phrases",
    "expected_tools",
    "bias_list",
    "max_call_seconds",
)


def agent_snapshot(agent: Agents) -> dict[str, Any]:
    """The agent as it was when the run was created (never its encrypted secrets)."""
    return {f: getattr(agent, f) for f in _SNAPSHOT_FIELDS}


@router.post(
    "/runs:regression",
    status_code=201,
    responses=errors(402, 404, 409),
    summary="Run the agent's regression tests with the given statuses (default: blocking)",
)
async def create_regression_run(
    body: RegressionRunCreate, key: WriteKey, session: Db
) -> RunCreated:
    agent = await get_or_404(session, Agents, body.agent_id, key.project_id, "Agent")
    statuses: list[RegressionStatus] = list(dict.fromkeys(body.statuses))
    rows = (
        await session.execute(
            select(RegressionTests.id, Scenarios.max_turns)
            .join(Scenarios, Scenarios.id == RegressionTests.scenario_id)
            .where(
                RegressionTests.agent_id == agent.id,
                RegressionTests.project_id == key.project_id,
                RegressionTests.status.in_(statuses),
            )
        )
    ).all()
    if not rows:
        raise ApiError(
            409,
            "conflict",
            f"The agent has no regression tests with status {', '.join(statuses)}",
            {"statuses": statuses},
        )
    estimate = estimate_run([max_turns for _, max_turns in rows])
    remaining = await remaining_budget(session)
    if remaining is not None and estimate.est_cost > remaining and not body.confirm_over_budget:
        raise ApiError(
            402,
            "budget_exceeded",
            "The estimated cost is above the remaining budget",
            {"estimate": estimate.model_dump(), "remaining_budget": remaining},
        )
    rubric = await session.scalar(select(RubricVersions.id).where(RubricVersions.is_active))
    run = TestRuns(
        project_id=key.project_id,
        agent_id=agent.id,
        name=body.name,
        kind="regression",
        status="queued",
        config={**body.config.model_dump(), "statuses": statuses},
        agent_snapshot=agent_snapshot(agent),
        summary={},
        rubric_version_id=rubric,
        estimated_cost=estimate.est_cost,
    )
    session.add(run)
    await flush(session, "Run could not be created")
    enqueue_event(
        session,
        make_envelope(
            RunRequested(
                run_id=run.id,
                agent_id=agent.id,
                kind="regression",
                repeats=1,
                seed=body.config.seed,
                regression_statuses=statuses,
            ),
            producer="api",
            correlation_id=str(run.id),
        ),
    )
    return RunCreated(id=run.id, status="queued", item_count=len(rows), estimate=estimate)


async def _out_many(session: AsyncSession, tests: list[RegressionTests]) -> list[RegressionTestOut]:
    titles = dict(
        (
            await session.execute(
                select(Scenarios.id, Scenarios.title).where(
                    Scenarios.id.in_([t.scenario_id for t in tests])
                )
            )
        ).all()
    )
    last = await latest_results(session, tests)
    items: list[RegressionTestOut] = []
    for t in tests:
        result = last.get(t.id)
        created: datetime = t.created_at
        items.append(
            RegressionTestOut(
                id=t.id,
                agent_id=t.agent_id,
                scenario_id=t.scenario_id,
                scenario_title=titles.get(t.scenario_id, ""),
                persona_id=t.persona_id,
                noise_profile_id=t.noise_profile_id,
                source_call_id=t.source_call_id,
                failure_type=t.failure_type,
                status=cast(RegressionStatus, t.status),
                baseline_score=float(t.baseline_score),
                tolerance=float(t.tolerance),
                notes=t.notes,
                created_at=created,
                last_run_id=result.run_id if result else None,
                last_score=result.score if result else None,
                last_passed=result.passed if result else None,
            )
        )
    return items


async def regression_out(session: AsyncSession, test: RegressionTests) -> RegressionTestOut:
    return (await _out_many(session, [test]))[0]


@router.get(
    "/regression-tests",
    summary="List regression tests with their last result",
)
async def list_regression_tests(
    key: ReadKey,
    session: Db,
    page: Pagination,
    agent_id: UUID | None = None,
    status: RegressionStatus | None = None,
) -> Page[RegressionTestOut]:
    conditions: list[Any] = [RegressionTests.project_id == key.project_id]
    if agent_id is not None:
        conditions.append(RegressionTests.agent_id == agent_id)
    if status is not None:
        conditions.append(RegressionTests.status == status)
    rows, nxt = await paginate(session, RegressionTests, conditions, page)
    return Page(items=await _out_many(session, rows), next_cursor=nxt)


@router.patch(
    "/regression-tests/{regression_test_id}",
    responses=errors(404),
    summary="Change status (blocking/scheduled/manual/retired), baseline, tolerance or notes",
)
async def update_regression_test(
    regression_test_id: UUID, body: RegressionTestUpdate, key: WriteKey, session: Db
) -> RegressionTestOut:
    row = await get_or_404(
        session, RegressionTests, regression_test_id, key.project_id, "Regression test"
    )
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:  # every column is NOT NULL: null means "leave as is"
            setattr(row, field, value)
    await flush(session, "Regression test could not be saved", refresh=row)
    return await regression_out(session, row)
