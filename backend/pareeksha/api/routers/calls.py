"""Calls and evaluations (docs/06-api-spec.md section 4)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy import select

from pareeksha.api.auth import WriteKey, scoped
from pareeksha.api.crud import flush, get_or_404
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, binary_response, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.outbox import enqueue_event
from pareeksha.api.stubs import not_implemented
from pareeksha.db.models import Calls, Evaluations, HumanReviews, RubricVersions, RunItems
from pareeksha.evaluation.rubric import DIMENSION_KEYS, RUBRIC_VERSION
from pareeksha.evaluation.scoring import overall_score
from pareeksha.events.schemas import CallCompleted, make_envelope
from pareeksha.regression.promote import promote_call as create_promotion
from pareeksha.schemas.calls import (
    AudioTrack,
    CallOut,
    CallStatus,
    CallSummaryOut,
    DimensionReview,
    HumanReviewOut,
    PromoteRequest,
    PromoteResult,
    ReevaluateRequest,
    ReviewCreate,
    Speaker,
)
from pareeksha.schemas.common import CallRef, CallSource, Page

router = APIRouter(tags=["calls"], responses=AUTH_ERRORS)


@router.get(
    "/calls",
    dependencies=[scoped("read")],
    summary="List calls (Audits page, review queue, Calibration)",
    description=(
        "Filters combine with AND. `source` may be repeated (e.g. `source=upload&source=import` "
        "for the Audits page). `needs_review=true&reviewed=false` is the human-review queue."
    ),
)
async def list_calls(
    page: Pagination,
    source: Annotated[list[CallSource] | None, Query()] = None,
    status: CallStatus | None = None,
    agent_id: UUID | None = None,
    run_id: UUID | None = None,
    needs_review: bool | None = None,
    reviewed: bool | None = None,
) -> Page[CallSummaryOut]:
    # STUB(API-04)
    not_implemented("API-04")


@router.get("/calls/{call_id}", dependencies=[scoped("read")], responses=errors(404))
async def get_call(call_id: UUID) -> CallOut:
    # STUB(API-04)
    not_implemented("API-04")


@router.get(
    "/calls/{call_id}/audio/{track}",
    dependencies=[scoped("read")],
    response_class=Response,
    responses={
        **binary_response("audio/wav", "WAV audio; supports HTTP Range requests"),
        206: {"description": "Partial content (Range request)"},
        **errors(404),
    },
    summary="Download a recording track",
)
async def get_call_audio(
    call_id: UUID,
    track: AudioTrack,
    range_: str | None = Header(default=None, alias="Range"),
) -> Response:
    # STUB(API-04)
    not_implemented("API-04")


@router.post(
    "/calls/{call_id}/reevaluate",
    status_code=202,
    responses=errors(404, 409),
    summary="Re-run the judge (optionally with another rubric version)",
)
async def reevaluate_call(
    call_id: UUID, key: WriteKey, session: Db, body: ReevaluateRequest | None = None
) -> CallRef:
    call = await get_or_404(session, Calls, call_id, key.project_id, "Call")
    version = body.rubric_version if body else None
    if version is not None:
        known = await session.scalar(
            select(RubricVersions.id).where(RubricVersions.version == version)
        )
        if known is None:
            raise ApiError(
                404, "not_found", "Rubric version not found", {"rubric_version": version}
            )
        if version != RUBRIC_VERSION:
            raise ApiError(
                400,
                "validation_error",
                f"This build evaluates with {RUBRIC_VERSION} only",
                {"rubric_version": version, "supported": RUBRIC_VERSION},
            )
    if call.status != "completed":
        raise ApiError(409, "conflict", f"The call is {call.status}; it has no transcript yet")
    run_id = None
    if call.run_item_id is not None:
        run_id = await session.scalar(
            select(RunItems.run_id).where(RunItems.id == call.run_item_id)
        )
    if call.source == "simulation" and (run_id is None or call.run_item_id is None):
        raise ApiError(409, "conflict", "The simulated call no longer belongs to a run item")
    enqueue_event(
        session,
        make_envelope(
            CallCompleted(
                call_id=call.id,
                source=call.source,
                agent_id=call.agent_id,
                run_id=run_id,
                run_item_id=call.run_item_id,
                end_reason=call.end_reason,
            ),
            producer="api",
            correlation_id=str(call.id),  # a fresh event id: re-evaluating is a new request
        ),
    )
    return CallRef(call_id=call.id)


@router.post(
    "/calls/{call_id}/review",
    status_code=201,
    responses=errors(404, 409),
    summary="Human review of the call's evaluation",
)
async def review_call(
    call_id: UUID, body: ReviewCreate, key: WriteKey, session: Db
) -> HumanReviewOut:
    call = await get_or_404(session, Calls, call_id, key.project_id, "Call")
    unknown = sorted(set(body.dimensions) - set(DIMENSION_KEYS))
    if unknown:
        raise ApiError(
            400,
            "validation_error",
            f"Unknown rubric dimensions: {', '.join(unknown)}",
            {"known": list(DIMENSION_KEYS)},
        )
    evaluation = (
        await session.scalars(
            select(Evaluations)
            .where(Evaluations.call_id == call.id, Evaluations.status == "ok")
            .order_by(Evaluations.created_at.desc())
            .limit(1)
        )
    ).first()
    if evaluation is None:
        raise ApiError(409, "conflict", "The call has no completed evaluation to review")
    scores = {k: v.score for k, v in body.dimensions.items()}
    review = HumanReviews(
        evaluation_id=evaluation.id,
        reviewer=body.reviewer,
        dimensions={k: {"score": v} for k, v in scores.items()},
        passed=body.passed,
        critical_failure=body.critical_failure,
        notes=body.notes,
        overall_score=overall_score(scores) if set(scores) == set(DIMENSION_KEYS) else None,
    )
    session.add(review)
    await flush(session, "This reviewer has already reviewed this evaluation", refresh=review)
    return HumanReviewOut(
        id=review.id,
        evaluation_id=review.evaluation_id,
        reviewer=review.reviewer,
        passed=review.passed,
        critical_failure=review.critical_failure,
        overall_score=None if review.overall_score is None else float(review.overall_score),
        dimensions={k: DimensionReview(score=v) for k, v in scores.items()},
        notes=review.notes,
        created_at=review.created_at,
    )


@router.post(
    "/calls/{call_id}/promote",
    status_code=201,
    responses=errors(404),
    summary="Promote a failed call to a regression test",
)
async def promote_call(
    call_id: UUID, body: PromoteRequest, key: WriteKey, session: Db
) -> PromoteResult:
    call = await get_or_404(session, Calls, call_id, key.project_id, "Call")
    promoted = await create_promotion(session, call, body, key.project_id)
    return PromoteResult(
        scenario_id=promoted.scenario_id, regression_test_id=promoted.regression_test_id
    )


@router.post(
    "/calls/{call_id}/speaker-map",
    status_code=202,
    dependencies=[scoped("audits:write")],
    responses=errors(404, 409),
    summary="Override diarization roles of an uploaded call; re-evaluates it",
)
async def set_speaker_map(call_id: UUID, body: dict[str, Speaker]) -> CallRef:
    # STUB(EVAL-04)
    not_implemented("EVAL-04")
