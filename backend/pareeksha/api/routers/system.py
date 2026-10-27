"""Health, usage, calibration, metrics and event schemas (docs/06-api-spec.md sections 6, 11)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from pareeksha.api.auth import ReadKey, scoped
from pareeksha.api.deps import AUTH_ERRORS, Db
from pareeksha.api.health import check_health
from pareeksha.api.stubs import not_implemented
from pareeksha.events.schemas import event_json_schemas
from pareeksha.events.settings import kafka_bootstrap
from pareeksha.ops import metrics
from pareeksha.schemas.system import (
    CalibrationOut,
    HealthOut,
    MetricsSummary,
    SpeechProvidersOut,
    UsageOut,
)
from pareeksha.speech.registry import provider_status

router = APIRouter(tags=["system"])
authed = APIRouter(tags=["system"], responses=AUTH_ERRORS)


@router.get(
    "/health",
    response_model=HealthOut,
    responses={503: {"model": HealthOut, "description": "a dependency is down"}},
    summary="Database and Kafka reachability (no auth)",
)
async def health() -> JSONResponse:
    result = await check_health()
    ok = result.db == "ok" and result.kafka == "ok"
    return JSONResponse(result.model_dump(), status_code=200 if ok else 503)


@authed.get(
    "/calibration",
    dependencies=[scoped("read")],
    summary="Judge vs human agreement (kappa, Spearman, per-dimension MAE)",
)
async def get_calibration(rubric_version: str | None = None) -> CalibrationOut:
    # STUB(API-05)
    not_implemented("API-05")


@authed.get(
    "/usage",
    summary="Aggregated api_usage and remaining budget",
)
async def get_usage(
    key: ReadKey,
    session: Db,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> UsageOut:
    return await metrics.usage(session, from_, to)


@authed.get(
    "/metrics/summary",
    summary="Consumer lag per group, outbox backlog, open DLQ count, credits used",
    responses={502: {"description": "upstream_error: Kafka unreachable"}},
)
async def get_metrics_summary(
    key: ReadKey, session: Db, bootstrap: Annotated[str, Depends(kafka_bootstrap)]
) -> MetricsSummary:
    return await metrics.metrics_summary(session, bootstrap)


@authed.get(
    "/events/schemas",
    dependencies=[scoped("read")],
    summary="JSON Schemas of the Kafka event envelope and every event payload",
    description=(
        "For consumers outside the API (e.g. a data team reading `evaluation.completed`). The "
        "Pydantic models in `pareeksha/events/schemas.py` are the source of truth."
    ),
)
async def get_event_schemas() -> dict[str, Any]:
    return event_json_schemas()


@authed.get(
    "/speech/providers",
    dependencies=[scoped("read")],
    summary="Speech (STT/TTS) providers: configured?, defaults, capabilities",
    description=(
        "Reports which of the pluggable speech providers have their credentials set in the "
        "environment, which ones are the `STT_PROVIDER` / `TTS_PROVIDER` defaults, and what each "
        "can do. Presence of a key is reported, never the key; validity is not checked."
    ),
)
async def get_speech_providers() -> SpeechProvidersOut:
    return SpeechProvidersOut(items=provider_status())
