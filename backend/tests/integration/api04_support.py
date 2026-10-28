"""Seeding helpers for the API-04 tests: runs, calls, turns, evaluations written as rows.

Rows are written the way the simulator / evaluator write them (EVAL-03b's stores use the same
columns, see ``docs/schema.sql``); the API under test only reads them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.db import models
from tests.conftest import Tenant
from tests.integration.runs_support import Fixture, make_fixture

Factory = async_sessionmaker[AsyncSession]


@dataclass
class SeededCall:
    call_id: uuid.UUID
    run_item_id: uuid.UUID | None
    evaluation_id: uuid.UUID | None = None


@dataclass
class SeededRun:
    run_id: uuid.UUID
    fx: Fixture
    item_ids: list[uuid.UUID] = field(default_factory=list)
    calls: list[SeededCall] = field(default_factory=list)


async def new_rubric(factory: Factory) -> uuid.UUID:
    async with factory() as session:
        rubric = models.RubricVersions(
            version=f"test-{uuid.uuid4().hex[:8]}", dimensions=[], prompt_hash="h"
        )
        session.add(rubric)
        await session.commit()
        return rubric.id


async def seed_run(
    api: Any,
    factory: Factory,
    tenant: Tenant,
    *,
    scores: list[tuple[float, bool] | None],
    fx: Fixture | None = None,
    status: str = "completed",
    summary: dict[str, Any] | None = None,
    rubric_id: uuid.UUID | None = None,
) -> SeededRun:
    """A run with ``len(scores)`` items; ``scores[i]`` is ``(overall_score, passed)`` or None.

    Item ``i`` is the i-th cell (scenario x persona x profile, in that nesting order) of the
    fixture; items with a score get a completed call and an evaluation, the others stay queued.
    """
    fx = fx or await make_fixture(api, tenant, scenarios=len(scores), personas=1, profiles=1)
    rubric_id = rubric_id or await new_rubric(factory)
    async with factory() as session:
        run = models.TestRuns(
            id=uuid.uuid4(),
            project_id=tenant.project_id,
            agent_id=uuid.UUID(fx.agent_id),
            name="seeded run",
            kind="matrix",
            status=status,
            config={"item_count": len(scores)},
            summary=summary or {},
            finished_at=datetime.now(UTC) if status in ("completed", "partial") else None,
        )
        session.add(run)
        await session.flush()
        seeded = SeededRun(run_id=run.id, fx=fx)
        for i, score in enumerate(scores):
            item = models.RunItems(
                run_id=run.id,
                scenario_id=uuid.UUID(fx.scenario_ids[i % len(fx.scenario_ids)]),
                persona_id=uuid.UUID(fx.persona_ids[0]),
                noise_profile_id=uuid.UUID(fx.noise_profile_ids[0]),
                seed=1000 + i,
                status="evaluated" if score else "queued",
            )
            session.add(item)
            await session.flush()
            seeded.item_ids.append(item.id)
            if score is None:
                continue
            call = models.Calls(
                project_id=tenant.project_id,
                agent_id=uuid.UUID(fx.agent_id),
                run_item_id=item.id,
                source="simulation",
                status="completed",
                language="kn-IN",
            )
            session.add(call)
            await session.flush()
            evaluation = models.Evaluations(
                call_id=call.id,
                rubric_version_id=rubric_id,
                judge_model="m",
                prompt_hash="h",
                overall_score=score[0],
                passed=score[1],
                critical_failure=False,
            )
            session.add(evaluation)
            await session.flush()
            seeded.calls.append(SeededCall(call.id, item.id, evaluation.id))
        await session.commit()
    return seeded


async def seed_full_call(
    factory: Factory,
    tenant: Tenant,
    agent_id: uuid.UUID | None,
    rubric_id: uuid.UUID,
    *,
    source: str = "simulation",
    status: str = "completed",
    needs_review: bool = False,
    reviewed: bool = False,
    score: float | None = 40.0,
    started_ago: timedelta = timedelta(0),
    recordings: dict[str, str] | None = None,
) -> SeededCall:
    """A call with turns, a tool call, metrics, checks, an evaluation and optionally a review."""
    async with factory() as session:
        call = models.Calls(
            project_id=tenant.project_id,
            agent_id=agent_id,
            source=source,
            status=status,
            language="kn-IN",
            end_reason="goal_achieved" if source == "simulation" else "upload",
            duration_ms=84200,
            started_at=datetime.now(UTC) - started_ago,
            speaker_map={"spk_0": "agent", "spk_1": "caller"} if source == "upload" else None,
            **(recordings or {}),
        )
        session.add(call)
        await session.flush()
        session.add_all(
            [
                models.Turns(
                    call_id=call.id,
                    idx=0,
                    speaker="agent",
                    text_="Namaskara",
                    text_masked="N",
                    start_ms=820,
                    end_ms=5400,
                ),
                models.Turns(
                    call_id=call.id,
                    idx=1,
                    speaker="caller",
                    text_="Already paid",
                    text_masked="A",
                    ground_truth_text="Sir, naanu already pay maadidini",
                    agent_heard_text="naalvattu saavira",
                    start_ms=6100,
                    end_ms=9300,
                    is_barge_in=True,
                    stt_confidence=0.912,
                    language_detected="kn-IN",
                ),
                models.ToolCalls(
                    call_id=call.id,
                    seq=0,
                    name="record_promise_to_pay",
                    arguments={"amount": 40000},
                    result={"ok": True},
                    at_ms=11200,
                    turn_idx=1,
                ),
                models.CallMetrics(
                    call_id=call.id,
                    first_greeting_ms=820,
                    response_latency_p50_ms=1040,
                    response_latency_p95_ms=2210,
                    barge_in_attempts=2,
                    barge_in_honoured=0,
                    silence_gaps_over_2s=1,
                    turn_count=2,
                    caller_asr_wer=0.18,
                ),
                models.DeterministicChecks(
                    call_id=call.id,
                    check_type="disclosure_present",
                    check_key="recording",
                    passed=False,
                    evidence_turns=[0, 2],
                    detail="No recording disclosure",
                ),
                models.DeterministicChecks(
                    call_id=call.id,
                    check_type="no_loop",
                    check_key="loop",
                    passed=True,
                ),
            ]
        )
        evaluation_id = None
        if score is not None:
            evaluation = models.Evaluations(
                call_id=call.id,
                rubric_version_id=rubric_id,
                judge_model="deepseek-v4-pro",
                prompt_hash="sha256:abc",
                dimensions={
                    "task_completion": {
                        "score": 1,
                        "evidence_turns": [1],
                        "reason": "Wrong amount.",
                    }
                },
                overall_score=score,
                passed=score >= 80,
                critical_failure=score < 50,
                needs_human_review=needs_review,
                review_reasons=["critical_failure"] if needs_review else [],
                failure_types=["wrong_fact"],
                summary="Misheard the amount.",
                confidence="high",
            )
            session.add(evaluation)
            await session.flush()
            evaluation_id = evaluation.id
            if reviewed:
                session.add(
                    models.HumanReviews(
                        evaluation_id=evaluation.id,
                        reviewer="preetham",
                        passed=False,
                        critical_failure=True,
                    )
                )
        await session.commit()
        return SeededCall(call.id, None, evaluation_id)
