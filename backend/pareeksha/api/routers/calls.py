"""Calls and evaluations (docs/06-api-spec.md section 4)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, binary_response, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.calls import (
    AudioTrack,
    CallOut,
    CallStatus,
    CallSummaryOut,
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
    dependencies=[scoped("runs:write")],
    responses=errors(404),
    summary="Re-run the judge (optionally with another rubric version)",
)
async def reevaluate_call(call_id: UUID, body: ReevaluateRequest | None = None) -> CallRef:
    # STUB(API-05)
    not_implemented("API-05")


@router.post(
    "/calls/{call_id}/review",
    status_code=201,
    dependencies=[scoped("runs:write")],
    responses=errors(404, 409),
    summary="Human review of the call's evaluation",
)
async def review_call(call_id: UUID, body: ReviewCreate) -> HumanReviewOut:
    # STUB(API-05)
    not_implemented("API-05")


@router.post(
    "/calls/{call_id}/promote",
    status_code=201,
    dependencies=[scoped("runs:write")],
    responses=errors(404),
    summary="Promote a failed call to a regression test",
)
async def promote_call(call_id: UUID, body: PromoteRequest) -> PromoteResult:
    # STUB(API-05)
    not_implemented("API-05")


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
