"""Promote a failed call to a regression test (FR-AU-5, FR-RG-1).

Creates a ``promoted`` scenario linked to the source call (``source_call_id``) and a regression
test pointing at it. For a simulated call the scenario is a copy of the one the call ran, with the
failure written into its success criteria, and the test keeps the call's persona and noise profile
so a re-run reproduces the same conditions. For an uploaded or imported call (no scenario) the
goal is taken from what the caller said (PII-masked text) and the criteria from the judge's
summary and the reviewer's notes; such a test has no persona, so it cannot be re-run until one is
assigned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.crud import flush
from pareeksha.api.errors import ApiError
from pareeksha.db.models import Calls, Evaluations, RegressionTests, RunItems, Scenarios, Turns
from pareeksha.schemas.calls import PromoteRequest

OPENING_TURNS = 3
MAX_GOAL_CHARS = 600


@dataclass(frozen=True)
class Promoted:
    scenario_id: uuid.UUID
    regression_test_id: uuid.UUID


def _failure_text(body: PromoteRequest, summary: str | None) -> str:
    parts = [f"Failure type: {body.failure_type}."]
    if summary:
        parts.append(f"Judge summary: {summary}")
    if body.notes:
        parts.append(f"Reviewer notes: {body.notes}")
    return " ".join(parts)


async def promote_call(
    session: AsyncSession, call: Calls, body: PromoteRequest, project_id: uuid.UUID
) -> Promoted:
    """Idempotent per (call, failure type): promoting again returns the existing pair."""
    if call.agent_id is None:
        raise ApiError(
            400,
            "validation_error",
            "The call has no agent; a regression test needs one",
            {"call_id": str(call.id)},
        )
    existing = (
        await session.scalars(
            select(RegressionTests).where(
                RegressionTests.source_call_id == call.id,
                RegressionTests.failure_type == body.failure_type,
            )
        )
    ).first()
    if existing is not None:
        return Promoted(existing.scenario_id, existing.id)

    summary = await session.scalar(
        select(Evaluations.summary)
        .where(Evaluations.call_id == call.id)
        .order_by(Evaluations.created_at.desc())
        .limit(1)
    )
    failure = _failure_text(body, summary)
    item = await session.get(RunItems, call.run_item_id) if call.run_item_id else None
    origin = await session.get(Scenarios, item.scenario_id) if item else None

    if origin is not None:
        scenario = Scenarios(
            project_id=project_id,
            agent_id=call.agent_id,
            title=f"{origin.title} [regression: {body.failure_type}]"[:300],
            caller_goal=origin.caller_goal,
            fixtures=origin.fixtures,
            reveal_rules=origin.reveal_rules,
            success_criteria=f"{origin.success_criteria}\nRegression: {failure}",
            must_say=origin.must_say,
            must_not_say=origin.must_not_say,
            expected_tool_calls=origin.expected_tool_calls,
            caller_speaks_first=origin.caller_speaks_first,
            max_turns=origin.max_turns,
            tags=[*dict.fromkeys([*origin.tags, "regression", body.failure_type])],
            source="promoted",
            source_call_id=call.id,
        )
    else:
        opening = (
            await session.scalars(
                select(Turns.text_masked)
                .where(Turns.call_id == call.id, Turns.speaker == "caller")
                .order_by(Turns.idx)
                .limit(OPENING_TURNS)
            )
        ).all()
        said = " / ".join(t for t in opening if t) or "(no caller speech was transcribed)"
        scenario = Scenarios(
            project_id=project_id,
            agent_id=call.agent_id,
            title=f"Regression from call {str(call.id)[:8]}: {body.failure_type}",
            caller_goal=f"Recreate the situation of call {call.id}. The caller opened with: {said}"[
                :MAX_GOAL_CHARS
            ],
            fixtures={},
            reveal_rules="",
            success_criteria=f"The agent avoids the failure seen in the original call. {failure}",
            must_say=[],
            must_not_say=[],
            expected_tool_calls=[],
            caller_speaks_first=False,
            max_turns=15,
            tags=["regression", body.failure_type],
            source="promoted",
            source_call_id=call.id,
        )
    session.add(scenario)
    await flush(session, "Scenario could not be saved")
    test = RegressionTests(
        project_id=project_id,
        agent_id=call.agent_id,
        scenario_id=scenario.id,
        persona_id=item.persona_id if item else None,
        noise_profile_id=item.noise_profile_id if item else None,
        source_call_id=call.id,
        failure_type=body.failure_type,
        status=body.status,
        baseline_score=body.baseline_score,
        notes=body.notes,
    )
    session.add(test)
    await flush(session, "Regression test could not be saved")
    return Promoted(scenario.id, test.id)
