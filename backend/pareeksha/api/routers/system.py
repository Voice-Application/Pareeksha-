"""Health, usage, calibration, metrics and event schemas (docs/06-api-spec.md sections 6, 11)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select

from pareeksha.api.auth import ReadKey, scoped
from pareeksha.api.deps import AUTH_ERRORS, Db
from pareeksha.api.health import check_health
from pareeksha.db.models import Calls, Evaluations, HumanReviews, RubricVersions
from pareeksha.db.queries import distinct_on
from pareeksha.evaluation.calibration import LabelPair, compute_calibration
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
    summary="Judge vs human agreement (kappa, Spearman, per-dimension MAE)",
    description=(
        "One human label per evaluation (the newest review) against the judge's verdict. "
        "Without `rubric_version` the active rubric is used (all versions when none is active)."
    ),
)
async def get_calibration(
    key: ReadKey, session: Db, rubric_version: str | None = None
) -> CalibrationOut:
    stmt = (
        select(Evaluations, HumanReviews)
        .join(HumanReviews, HumanReviews.evaluation_id == Evaluations.id)
        .join(Calls, Calls.id == Evaluations.call_id)
        .join(RubricVersions, RubricVersions.id == Evaluations.rubric_version_id)
        .where(
            Calls.project_id == key.project_id,
            Evaluations.status == "ok",
            Evaluations.passed.is_not(None),
        )
        .order_by(Evaluations.id, HumanReviews.created_at.desc())
    )
    stmt = distinct_on(stmt, Evaluations.id)
    if rubric_version is not None:
        stmt = stmt.where(RubricVersions.version == rubric_version)
    elif await session.scalar(select(RubricVersions.id).where(RubricVersions.is_active)):
        stmt = stmt.where(RubricVersions.is_active)
    pairs = [
        LabelPair(
            judge_passed=bool(ev.passed),
            human_passed=hr.passed,
            judge_score=None if ev.overall_score is None else float(ev.overall_score),
            human_score=None if hr.overall_score is None else float(hr.overall_score),
            judge_dimensions=_scores(ev.dimensions),
            human_dimensions=_scores(hr.dimensions),
        )
        for ev, hr in (await session.execute(stmt)).all()
    ]
    result = compute_calibration(pairs)
    return CalibrationOut(
        n=result.n,
        kappa_pass_fail=result.kappa_pass_fail,
        spearman_overall=result.spearman_overall,
        dimension_mae=result.dimension_mae,
    )


def _scores(dimensions: object) -> dict[str, int]:
    """``{dimension: {"score": n, ...}}`` (as stored for judge and human) -> ``{dimension: n}``."""
    if not isinstance(dimensions, dict):
        return {}
    return {
        k: int(v["score"]) for k, v in dimensions.items() if isinstance(v, dict) and "score" in v
    }


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
