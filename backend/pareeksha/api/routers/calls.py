"""Calls and evaluations (docs/06-api-spec.md section 4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import delete, select

from pareeksha.api.auth import ReadKey, WriteAuditKey, WriteKey
from pareeksha.api.crud import flush, get_or_404
from pareeksha.api.deps import AUTH_ERRORS, Blobs, Db, Pagination, binary_response, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.outbox import enqueue_event
from pareeksha.audit.pipeline import primary_language, stt_blob_key
from pareeksha.audit.turns import LabelledSegment, build_turns, labels_in_order
from pareeksha.calls import service
from pareeksha.calls.audio import audio_response
from pareeksha.db.models import Calls, Evaluations, HumanReviews, RubricVersions, RunItems, Turns
from pareeksha.evaluation.pii import mask_pii
from pareeksha.evaluation.rubric import DIMENSION_KEYS, RUBRIC_VERSION
from pareeksha.evaluation.scoring import overall_score
from pareeksha.events.outbox import enqueue_session
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
from pareeksha.schemas.common import CallRef, CallSource, ErrorResponse, Page
from pareeksha.storage.blob import BlobNotFoundError

router = APIRouter(tags=["calls"], responses=AUTH_ERRORS)


@router.get(
    "/calls",
    summary="List calls (Audits page, review queue, Calibration)",
    description=(
        "Filters combine with AND. `source` may be repeated (e.g. `source=upload&source=import` "
        "for the Audits page). `needs_review=true&reviewed=false` is the human-review queue."
    ),
)
async def list_calls(
    key: ReadKey,
    session: Db,
    page: Pagination,
    source: Annotated[list[CallSource] | None, Query()] = None,
    status: CallStatus | None = None,
    agent_id: UUID | None = None,
    run_id: UUID | None = None,
    needs_review: bool | None = None,
    reviewed: bool | None = None,
) -> Page[CallSummaryOut]:
    return await service.list_calls(
        session,
        key.project_id,
        page,
        source=list(source) if source else None,
        status=status,
        agent_id=agent_id,
        run_id=run_id,
        needs_review=needs_review,
        reviewed=reviewed,
    )


@router.get("/calls/{call_id}", responses=errors(404))
async def get_call(call_id: UUID, key: ReadKey, session: Db, request: Request) -> CallOut:
    def audio_url(cid: UUID, track: str) -> str:
        return str(request.app.url_path_for("get_call_audio", call_id=cid, track=track))

    return await service.get_call(session, key.project_id, call_id, audio_url)


@router.get(
    "/calls/{call_id}/audio/{track}",
    response_class=Response,
    responses={
        **binary_response("audio/wav", "WAV audio; supports HTTP Range requests"),
        206: {"description": "Partial content (Range request)"},
        **errors(404),
        416: {"model": ErrorResponse, "description": "range_not_satisfiable"},
    },
    summary="Download a recording track",
)
async def get_call_audio(
    call_id: UUID,
    track: AudioTrack,
    key: ReadKey,
    session: Db,
    range_: str | None = Header(default=None, alias="Range"),
) -> Response:
    blob_path = await service.recording_path(session, key.project_id, call_id, track)
    return audio_response(blob_path, range_)


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
    responses=errors(404, 409),
    summary="Override diarization roles of an uploaded call; re-evaluates it",
)
async def set_speaker_map(
    call_id: UUID, body: dict[str, Speaker], key: WriteAuditKey, session: Db, blobs: Blobs
) -> CallRef:
    """Rebuild the turns from the stored diarized segments with the given roles, then ask the
    evaluator to judge the call again (same rubric version; the evaluation row is replaced)."""
    stmt = (
        select(Calls)
        .where(Calls.id == call_id, Calls.project_id == key.project_id)
        .with_for_update()
    )
    call = (await session.scalars(stmt)).one_or_none()
    if call is None:
        raise ApiError(404, "not_found", "Call not found", {"id": str(call_id)})
    if call.source == "simulation":
        raise ApiError(409, "conflict", "A speaker map applies to uploaded or imported calls only")
    if call.status != "completed":
        raise ApiError(409, "conflict", f"The call is {call.status}; wait until it is completed")
    try:
        stored = json.loads(await blobs.get(stt_blob_key(call.source, call.id)))
    except BlobNotFoundError as exc:
        raise ApiError(409, "conflict", "The call has no stored transcript to re-map") from exc
    segments = [LabelledSegment.from_dict(s) for s in stored["segments"]]
    labels = set(labels_in_order(segments))
    previous = cast("dict[str, Speaker]", call.speaker_map or {})
    unknown = sorted(set(body) - labels)
    if unknown:
        raise ApiError(
            400,
            "validation_error",
            "speaker-map names speakers this call does not have",
            {"unknown": unknown, "speakers": sorted(labels)},
        )
    roles = {label: body.get(label) or previous.get(label) for label in labels}
    missing = sorted(label for label, role in roles.items() if role is None)
    if missing or (len(labels) > 1 and set(roles.values()) != {"agent", "caller"}):
        raise ApiError(
            400,
            "validation_error",
            "every speaker needs a role and a call with several speakers needs an agent "
            "and a caller",
            {"missing": missing, "speakers": sorted(labels)},
        )
    final = cast("dict[str, Speaker]", roles)

    await session.execute(delete(Turns).where(Turns.call_id == call.id))
    language = primary_language(call.language or "") or None
    for t in build_turns(segments, final):
        session.add(
            Turns(
                call_id=call.id,
                idx=t.idx,
                speaker=t.speaker,
                text_=t.text,
                text_masked=mask_pii(t.text),
                start_ms=t.start_ms,
                end_ms=t.end_ms,
                is_barge_in=t.is_barge_in,
                language_detected=language,
            )
        )
    call.speaker_map = final
    call.event_log = [
        *cast("list[Any]", call.event_log),
        {
            "event": "speaker_map_override",
            "at": datetime.now(UTC).isoformat(),
            "previous": previous,
            "roles": final,
        },
    ]
    origin: Literal["upload", "import"] = "upload" if call.source == "upload" else "import"
    enqueue_session(
        session,
        make_envelope(
            CallCompleted(
                call_id=call.id, source=origin, agent_id=call.agent_id, end_reason=origin
            ),
            producer="api",
            correlation_id=str(call.id),
        ),
    )
    return CallRef(call_id=call.id)
