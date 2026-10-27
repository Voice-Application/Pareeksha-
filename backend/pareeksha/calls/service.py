"""Call reads: the list for the Audits page / review queue and the call detail (API-04).

A call's evaluation is its latest ``evaluations`` row (re-evaluation with another rubric adds a
row). ``human_reviewed`` means a ``human_reviews`` row exists for that evaluation.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import Select, exists, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.crud import paginate_rows
from pareeksha.api.deps import PageParams
from pareeksha.api.errors import ApiError
from pareeksha.db.models import (
    CallMetrics,
    Calls,
    DeterministicChecks,
    Evaluations,
    HumanReviews,
    RubricVersions,
    RunItems,
    ToolCalls,
    Turns,
)
from pareeksha.schemas.calls import (
    CallMetricsOut,
    CallOut,
    CallSummaryOut,
    CheckOut,
    DimensionScore,
    EvaluationOut,
    Recordings,
    ToolCallOut,
    TurnOut,
)
from pareeksha.schemas.common import Page

_TRACK_COLUMNS = {
    "mixed": Calls.recording_mixed,
    "caller": Calls.recording_caller,
    "agent": Calls.recording_agent,
    "original": Calls.recording_original,
}


def latest_evaluations() -> Any:
    """Subquery: the newest evaluation of every call (``DISTINCT ON (call_id)``)."""
    return (
        select(Evaluations)
        .ext(distinct_on(Evaluations.call_id))
        .order_by(Evaluations.call_id, Evaluations.created_at.desc(), Evaluations.id.desc())
        .subquery("latest_evaluation")
    )


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


async def list_calls(
    session: AsyncSession,
    project_id: uuid.UUID,
    page: PageParams,
    *,
    source: list[str] | None,
    status: str | None,
    agent_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    needs_review: bool | None,
    reviewed: bool | None,
) -> Page[CallSummaryOut]:
    ev = latest_evaluations()
    reviewed_expr = exists().where(HumanReviews.evaluation_id == ev.c.id)
    stmt: Select[Any] = (
        select(
            Calls,
            RunItems.run_id.label("run_id"),
            ev.c.id.label("ev_id"),
            ev.c.overall_score.label("ev_score"),
            ev.c.passed.label("ev_passed"),
            ev.c.critical_failure.label("ev_critical"),
            ev.c.needs_human_review.label("ev_needs_review"),
            ev.c.review_reasons.label("ev_reasons"),
            ev.c.failure_types.label("ev_failure_types"),
            reviewed_expr.label("human_reviewed"),
        )
        .outerjoin(RunItems, RunItems.id == Calls.run_item_id)
        .outerjoin(ev, ev.c.call_id == Calls.id)
        .where(Calls.project_id == project_id)
    )
    if source:
        stmt = stmt.where(Calls.source.in_(source))
    if status is not None:
        stmt = stmt.where(Calls.status == status)
    if agent_id is not None:
        stmt = stmt.where(Calls.agent_id == agent_id)
    if run_id is not None:
        stmt = stmt.where(RunItems.run_id == run_id)
    if needs_review is not None:
        stmt = stmt.where(func.coalesce(ev.c.needs_human_review, False) == needs_review)
    if reviewed is not None:
        stmt = stmt.where(reviewed_expr == reviewed)
    rows, next_cursor = await paginate_rows(
        session,
        stmt,
        Calls.started_at,
        Calls.id,
        page,
        key_of=lambda row: (row.Calls.started_at, row.Calls.id),
    )
    return Page(items=[_summary(row) for row in rows], next_cursor=next_cursor)


def _summary(row: Any) -> CallSummaryOut:
    call: Calls = row.Calls
    return CallSummaryOut(
        id=call.id,
        source=cast("Any", call.source),
        status=cast("Any", call.status),
        agent_id=call.agent_id,
        run_id=row.run_id,
        language=call.language,
        duration_ms=call.duration_ms,
        started_at=call.started_at,
        overall_score=_float(row.ev_score),
        passed=row.ev_passed,
        critical_failure=row.ev_critical,
        needs_human_review=row.ev_needs_review,
        review_reasons=list(row.ev_reasons or []),
        failure_types=list(row.ev_failure_types or []),
        human_reviewed=bool(row.human_reviewed),
    )


async def get_call(
    session: AsyncSession,
    project_id: uuid.UUID,
    call_id: uuid.UUID,
    audio_url: Callable[[uuid.UUID, str], str],
) -> CallOut:
    row = (
        await session.execute(
            select(Calls, RunItems.run_id)
            .outerjoin(RunItems, RunItems.id == Calls.run_item_id)
            .where(Calls.id == call_id, Calls.project_id == project_id)
        )
    ).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "Call not found", {"id": str(call_id)})
    call, run_id = row

    turns = (
        await session.scalars(select(Turns).where(Turns.call_id == call_id).order_by(Turns.idx))
    ).all()
    tool_calls = (
        await session.scalars(
            select(ToolCalls).where(ToolCalls.call_id == call_id).order_by(ToolCalls.seq)
        )
    ).all()
    metrics = await session.get(CallMetrics, call_id)
    checks = (
        await session.scalars(
            select(DeterministicChecks)
            .where(DeterministicChecks.call_id == call_id)
            .order_by(DeterministicChecks.check_type, DeterministicChecks.check_key)
        )
    ).all()
    evaluation = (
        await session.execute(
            select(Evaluations, RubricVersions.version)
            .join(RubricVersions, RubricVersions.id == Evaluations.rubric_version_id)
            .where(Evaluations.call_id == call_id)
            .order_by(Evaluations.created_at.desc(), Evaluations.id.desc())
            .limit(1)
        )
    ).one_or_none()

    return CallOut(
        id=call.id,
        source=cast("Any", call.source),
        status=cast("Any", call.status),
        agent_id=call.agent_id,
        run_id=run_id,
        run_item_id=call.run_item_id,
        language=call.language,
        end_reason=cast("Any", call.end_reason),
        duration_ms=call.duration_ms,
        started_at=call.started_at,
        recordings=Recordings(
            **{
                track: audio_url(call.id, track) if getattr(call, f"recording_{track}") else None
                for track in _TRACK_COLUMNS
            }
        ),
        turns=[
            TurnOut(
                idx=t.idx,
                speaker=cast("Any", t.speaker),
                text=t.text_,
                start_ms=t.start_ms,
                end_ms=t.end_ms,
                ground_truth_text=t.ground_truth_text,
                agent_heard_text=t.agent_heard_text,
                language_detected=t.language_detected,
                stt_confidence=_float(t.stt_confidence),
                is_barge_in=t.is_barge_in,
            )
            for t in turns
        ],
        tool_calls=[
            ToolCallOut(
                seq=t.seq,
                name=t.name,
                arguments=cast("dict[str, Any]", t.arguments or {}),
                result=cast("dict[str, Any] | None", t.result),
                at_ms=t.at_ms,
                turn_idx=t.turn_idx,
            )
            for t in tool_calls
        ],
        metrics=None if metrics is None else _metrics(metrics),
        checks=[
            CheckOut(
                check_type=cast("Any", c.check_type),
                check_key=c.check_key,
                must_pass=c.must_pass,
                passed=c.passed,
                evidence_turns=list(c.evidence_turns or []),
                detail=c.detail,
            )
            for c in checks
        ],
        evaluation=None if evaluation is None else _evaluation(*evaluation),
        speaker_map=cast("Any", call.speaker_map),
    )


def _metrics(m: CallMetrics) -> CallMetricsOut:
    return CallMetricsOut(
        first_greeting_ms=m.first_greeting_ms,
        response_latency_p50_ms=m.response_latency_p50_ms,
        response_latency_p90_ms=m.response_latency_p90_ms,
        response_latency_p95_ms=m.response_latency_p95_ms,
        response_latency_max_ms=m.response_latency_max_ms,
        barge_in_attempts=m.barge_in_attempts,
        barge_in_honoured=m.barge_in_honoured,
        agent_stop_time_p50_ms=m.agent_stop_time_p50_ms,
        silence_gaps_over_2s=m.silence_gaps_over_2s,
        turn_count=m.turn_count,
        agent_talk_ratio=_float(m.agent_talk_ratio),
        repeated_utterances=m.repeated_utterances,
        caller_asr_wer=_float(m.caller_asr_wer),
        latency_is_approximate=m.latency_is_approximate,
    )


def _evaluation(e: Evaluations, rubric_version: str) -> EvaluationOut:
    dimensions = cast("dict[str, dict[str, Any]]", e.dimensions or {})
    return EvaluationOut(
        id=e.id,
        rubric_version=rubric_version,
        judge_model=e.judge_model,
        prompt_hash=e.prompt_hash,
        status=cast("Any", e.status),
        overall_score=_float(e.overall_score),
        passed=e.passed,
        critical_failure=e.critical_failure,
        needs_human_review=e.needs_human_review,
        review_reasons=list(e.review_reasons or []),
        failure_types=cast("Any", list(e.failure_types or [])),
        dimensions={k: DimensionScore.model_validate(v) for k, v in dimensions.items()},
        summary=e.summary,
        confidence=cast("Any", e.confidence),
    )


async def recording_path(
    session: AsyncSession, project_id: uuid.UUID, call_id: uuid.UUID, track: str
) -> str:
    """The stored blob path of one track; 404 when the call or the track does not exist."""
    column = _TRACK_COLUMNS[track]
    row = (
        await session.execute(
            select(column).where(Calls.id == call_id, Calls.project_id == project_id)
        )
    ).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "Call not found", {"id": str(call_id)})
    if not row[0]:
        raise ApiError(
            404,
            "not_found",
            f"The call has no {track} recording",
            {"id": str(call_id), "track": track},
        )
    return str(row[0])
