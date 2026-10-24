"""Runs (docs/06-api-spec.md section 3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Response

from pareeksha.api.auth import ReadKey, WriteKey, scoped
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, binary_response, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.runs import service
from pareeksha.schemas.common import Page
from pareeksha.schemas.runs import (
    RunCompareOut,
    RunCreate,
    RunCreated,
    RunEstimateOut,
    RunItemOut,
    RunKind,
    RunOut,
    RunStatus,
)

router = APIRouter(tags=["runs"], responses=AUTH_ERRORS)

_SSE_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "text/event-stream. First a `snapshot` event, then `item.status`, `call.evaluated` "
            "and `run.completed`; a comment heartbeat every 15 s. Reconnect with `Last-Event-ID`; "
            "the server sends a fresh `snapshot`. The `data:` payloads are the Sse* schemas."
        ),
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}


@router.post(
    "/runs",
    status_code=201,
    responses=errors(402, 404, 409),
    summary="Create a run (writes the run and its run.requested outbox event in one transaction)",
)
async def create_run(body: RunCreate, key: WriteKey, session: Db) -> RunCreated:
    return await service.create_run(session, key.project_id, body)


@router.post(
    "/runs:estimate",
    responses=errors(404, 409),
    summary="Dry estimate of a run (item count, cost, budget check); creates nothing",
)
async def estimate_run(body: RunCreate, key: ReadKey, session: Db) -> RunEstimateOut:
    return await service.estimate(session, key.project_id, body)


@router.get("/runs", summary="List runs")
async def list_runs(
    key: ReadKey,
    session: Db,
    page: Pagination,
    agent_id: UUID | None = None,
    status: RunStatus | None = None,
    kind: RunKind | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Page[RunOut]:
    return await service.list_runs(
        session,
        key.project_id,
        page,
        agent_id=agent_id,
        status=status,
        kind=kind,
        created_from=created_from,
        created_to=created_to,
    )


# Declared before /runs/{run_id} so "compare" is never parsed as a run id.
@router.get(
    "/runs/compare",
    dependencies=[scoped("read")],
    responses=errors(404),
    summary="Per-cell score deltas between two runs",
)
async def compare_runs(base: UUID, head: UUID) -> RunCompareOut:
    # STUB(API-04)
    not_implemented("API-04")


@router.get("/runs/{run_id}", responses=errors(404))
async def get_run(run_id: UUID, key: ReadKey, session: Db) -> RunOut:
    return await service.get_run(session, key.project_id, run_id)


@router.get(
    "/runs/{run_id}/events",
    dependencies=[scoped("read")],
    response_class=Response,
    responses={**_SSE_RESPONSE, **errors(404)},
    summary="Live progress (Server-Sent Events)",
)
async def stream_run_events(
    run_id: UUID,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> Response:
    # STUB(API-04)
    not_implemented("API-04")


@router.get(
    "/runs/{run_id}/items",
    responses=errors(404),
    summary="Rows for the matrix view",
)
async def list_run_items(
    run_id: UUID, key: ReadKey, session: Db, page: Pagination
) -> Page[RunItemOut]:
    return await service.list_items(session, key.project_id, run_id, page)


@router.post(
    "/runs/{run_id}/cancel",
    status_code=202,
    responses=errors(404, 409),
    summary="Cancel a run (409 if already finished)",
)
async def cancel_run(run_id: UUID, key: WriteKey, session: Db) -> RunOut:
    return await service.cancel_run(session, key.project_id, run_id)


@router.get(
    "/runs/{run_id}/report",
    dependencies=[scoped("read")],
    response_class=Response,
    responses={**binary_response("text/html", "Exportable HTML report"), **errors(404)},
    summary="Exportable HTML report of a run",
)
async def get_run_report(run_id: UUID) -> Response:
    # STUB(API-04)
    not_implemented("API-04")
