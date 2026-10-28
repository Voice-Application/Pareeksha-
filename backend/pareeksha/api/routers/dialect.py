"""Dialect datasets and reports (docs/06-api-spec.md section 5; FR-DI-1..6)."""

from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, File, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.auth import ReadKey, WriteKey
from pareeksha.api.crud import flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, binary_response, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.outbox import enqueue_event
from pareeksha.db.models import (
    AsrResults,
    DialectDatasets,
    DialectReports,
    DialectSamples,
    NoiseProfiles,
)
from pareeksha.dialect.manifest import collect_clips, open_zip, parse_manifest
from pareeksha.dialect.pipeline import engine_provider
from pareeksha.dialect.report import render_html
from pareeksha.events.schemas import DialectClipRequested, make_envelope
from pareeksha.schemas.common import Page
from pareeksha.schemas.dialect import (
    ClipResultOut,
    DatasetCreate,
    DatasetOut,
    DialectEvaluateAccepted,
    DialectEvaluateRequest,
    DialectReportOut,
    DialectReportSummaryOut,
    EngineAggregate,
    RejectedRow,
    ReportProgress,
    SamplesUploadResult,
    TopError,
)

router = APIRouter(tags=["dialect"], responses=AUTH_ERRORS)

_DUPLICATE = "A dataset with this name already exists"
META = "_meta"


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data/runtime"))


# ------------------------------------------------------------------------------- datasets


async def _sample_count(session: AsyncSession, dataset_id: UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(DialectSamples)
        .where(DialectSamples.dataset_id == dataset_id)
    )
    return int(await session.scalar(stmt) or 0)


async def _dataset_out(session: AsyncSession, row: DialectDatasets) -> DatasetOut:
    return DatasetOut(
        id=row.id,
        name=row.name,
        description=row.description,
        sample_count=await _sample_count(session, row.id),
        created_at=row.created_at,
    )


@router.post("/dialect-datasets", status_code=201, responses=errors(409))
async def create_dialect_dataset(body: DatasetCreate, key: WriteKey, session: Db) -> DatasetOut:
    row = DialectDatasets(project_id=key.project_id, name=body.name, description=body.description)
    session.add(row)
    await flush(session, _DUPLICATE, refresh=row)
    return await _dataset_out(session, row)


@router.get("/dialect-datasets", summary="List datasets")
async def list_dialect_datasets(key: ReadKey, session: Db, page: Pagination) -> Page[DatasetOut]:
    rows, nxt = await paginate(
        session, DialectDatasets, [DialectDatasets.project_id == key.project_id], page
    )
    return Page(items=[await _dataset_out(session, r) for r in rows], next_cursor=nxt)


@router.post(
    "/dialect-datasets/{dataset_id}/samples",
    responses=errors(404, 413),
    summary="Import a manifest CSV and a ZIP of clips; rows without consent are rejected",
)
async def upload_dialect_samples(
    dataset_id: UUID,
    manifest: Annotated[
        UploadFile,
        File(
            description=(
                "CSV: file,reference_text,language,dialect_label,speaker_id,consent,domain_terms"
            )
        ),
    ],
    clips: Annotated[UploadFile, File(description="ZIP with the files named in the manifest")],
    key: WriteKey,
    session: Db,
) -> SamplesUploadResult:
    await get_or_404(session, DialectDatasets, dataset_id, key.project_id, "Dataset")
    rows = parse_manifest(await manifest.read())
    archive = open_zip(await clips.read())
    accepted, rejected = collect_clips(rows, archive)
    folder = data_dir() / "dialect" / str(dataset_id)
    folder.mkdir(parents=True, exist_ok=True)
    for clip in accepted:
        sample_id = uuid.uuid4()
        relative = f"dialect/{dataset_id}/{sample_id}.wav"
        (data_dir() / relative).write_bytes(clip.wav)
        session.add(
            DialectSamples(
                id=sample_id,
                dataset_id=dataset_id,
                audio_path=relative,
                reference_text=clip.row.reference_text,
                language=clip.row.language,
                dialect_label=clip.row.dialect_label,
                speaker_id=clip.row.speaker_id,
                duration_ms=clip.duration_ms,
                consent=True,
                domain_terms=clip.row.domain_terms,
            )
        )
    await flush(session, "Samples could not be saved")
    return SamplesUploadResult(
        accepted=len(accepted),
        rejected=[RejectedRow(row=r.row, reason=r.reason) for r in rejected],
    )


# ------------------------------------------------------------------------------- evaluate


def clip_event_id(report_id: UUID, sample_id: UUID, noise_profile_id: UUID) -> UUID:
    """Deterministic, so a retried request cannot enqueue the same clip twice."""
    return uuid.uuid5(report_id, f"clip:{sample_id}:{noise_profile_id}")


@router.post(
    "/dialect-datasets/{dataset_id}/evaluate",
    status_code=202,
    responses=errors(404, 409),
    summary="Evaluate every clip under every noise condition",
)
async def evaluate_dialect_dataset(
    dataset_id: UUID, body: DialectEvaluateRequest, key: WriteKey, session: Db
) -> DialectEvaluateAccepted:
    await get_or_404(session, DialectDatasets, dataset_id, key.project_id, "Dataset")
    engines = list(dict.fromkeys(body.engines))
    for engine in engines:
        try:
            engine_provider(engine)
        except ValueError as exc:
            raise ApiError(400, "validation_error", str(exc), {"engine": engine}) from exc
    condition_ids = list(dict.fromkeys(body.noise_profile_ids))
    found = set(
        (
            await session.scalars(
                select(NoiseProfiles.id).where(
                    NoiseProfiles.project_id == key.project_id, NoiseProfiles.id.in_(condition_ids)
                )
            )
        ).all()
    )
    missing = [str(c) for c in condition_ids if c not in found]
    if missing:
        raise ApiError(404, "not_found", "Noise profile not found", {"ids": missing})
    sample_ids = list(
        (
            await session.scalars(
                select(DialectSamples.id)
                .where(DialectSamples.dataset_id == dataset_id)
                .order_by(DialectSamples.created_at, DialectSamples.id)
            )
        ).all()
    )
    if not sample_ids:
        raise ApiError(409, "conflict", "The dataset has no samples; upload a manifest first")
    expected = len(sample_ids) * len(condition_ids) * len(engines)
    report = DialectReports(
        id=uuid.uuid4(),
        dataset_id=dataset_id,
        conditions=condition_ids,
        engines=engines,
        aggregates={
            META: {"expected_results": expected, "sample_ids": [str(s) for s in sample_ids]}
        },
    )
    session.add(report)
    await flush(session, "Report could not be created")
    for sample_id in sample_ids:
        for noise_id in condition_ids:
            payload = DialectClipRequested(
                report_id=report.id,
                dataset_id=dataset_id,
                sample_id=sample_id,
                noise_profile_id=noise_id,
                engines=engines,
                expected_results=expected,
            )
            enqueue_event(
                session,
                make_envelope(
                    payload,
                    producer="api",
                    correlation_id=str(report.id),
                    event_id=clip_event_id(report.id, sample_id, noise_id),
                ),
            )
    return DialectEvaluateAccepted(report_id=report.id, expected_results=expected)


# ------------------------------------------------------------------------------- reports


async def _project_report(session: AsyncSession, report_id: UUID, project_id: UUID) -> Any:
    stmt = (
        select(DialectReports)
        .join(DialectDatasets, DialectDatasets.id == DialectReports.dataset_id)
        .where(DialectReports.id == report_id, DialectDatasets.project_id == project_id)
    )
    row = (await session.scalars(stmt)).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "Report not found", {"id": str(report_id)})
    return row


def _meta(row: DialectReports) -> dict[str, Any]:
    aggregates = cast(dict[str, Any], row.aggregates)
    return dict(aggregates.get(META) or {})


def _complete(row: DialectReports) -> bool:
    return bool(_meta(row).get("complete"))


async def _progress(session: AsyncSession, row: DialectReports) -> ReportProgress:
    meta = _meta(row)
    expected = int(meta.get("expected_results", 0))
    if _complete(row):
        return ReportProgress(done=expected, expected_results=expected)
    sample_ids = [UUID(s) for s in meta.get("sample_ids", [])]
    stmt = select(
        func.count(
            func.distinct(
                func.row(AsrResults.sample_id, AsrResults.noise_profile_id, AsrResults.engine)
            )
        )
    ).where(
        AsrResults.sample_id.in_(sample_ids),
        AsrResults.noise_profile_id.in_(row.conditions),
        AsrResults.engine.in_(row.engines),
    )
    done = int(await session.scalar(stmt) or 0) if sample_ids else 0
    return ReportProgress(done=min(done, expected), expected_results=expected)


@router.get("/dialect-reports", summary="List reports")
async def list_dialect_reports(
    key: ReadKey, session: Db, page: Pagination, dataset_id: UUID | None = None
) -> Page[DialectReportSummaryOut]:
    own = select(DialectDatasets.id).where(DialectDatasets.project_id == key.project_id)
    conditions: list[Any] = [DialectReports.dataset_id.in_(own)]
    if dataset_id is not None:
        conditions.append(DialectReports.dataset_id == dataset_id)
    rows, nxt = await paginate(session, DialectReports, conditions, page)
    items = [
        DialectReportSummaryOut(
            id=r.id,
            dataset_id=r.dataset_id,
            engines=list(r.engines),
            conditions=list(r.conditions),
            progress=await _progress(session, r),
            created_at=r.created_at,
        )
        for r in rows
    ]
    return Page(items=items, next_cursor=nxt)


def _offset_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode().rstrip("=")


def _read_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        return max(0, int(json.loads(raw)["o"]))
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise ApiError(400, "validation_error", "Invalid cursor", {"cursor": cursor}) from exc


@router.get(
    "/dialect-reports/{report_id}/clips",
    responses=errors(404),
    summary="Worst clips first, for the heatmap drill-down",
)
async def list_dialect_report_clips(
    report_id: UUID,
    key: ReadKey,
    session: Db,
    page: Pagination,
    dialect: str | None = None,
    condition: str | None = None,
    engine: str | None = None,
) -> Page[ClipResultOut]:
    report = await _project_report(session, report_id, key.project_id)
    sample_ids = [UUID(s) for s in _meta(report).get("sample_ids", [])]
    stmt = (
        select(AsrResults, DialectSamples, NoiseProfiles.name)
        .join(DialectSamples, DialectSamples.id == AsrResults.sample_id)
        .join(NoiseProfiles, NoiseProfiles.id == AsrResults.noise_profile_id)
        .where(
            AsrResults.sample_id.in_(sample_ids),
            AsrResults.noise_profile_id.in_(report.conditions),
            AsrResults.engine.in_(report.engines),
        )
    )
    if dialect:
        stmt = stmt.where(DialectSamples.dialect_label == dialect)
    if condition:
        stmt = stmt.where(NoiseProfiles.name == condition)
    if engine:
        stmt = stmt.where(AsrResults.engine == engine)
    offset = _read_offset(page.cursor)
    stmt = (
        stmt.order_by(AsrResults.wer.desc(), AsrResults.cer.desc(), AsrResults.id)
        .offset(offset)
        .limit(page.limit + 1)
    )
    result = (await session.execute(stmt)).all()
    items = [
        ClipResultOut(
            sample_id=sample.id,
            dialect_label=sample.dialect_label,
            condition=noise_name,
            engine=asr.engine,
            reference_text=sample.reference_text,
            hypothesis_text=asr.hypothesis_text,
            wer=float(asr.wer),
            cer=float(asr.cer),
            entity_total=asr.entity_total,
            entity_correct=asr.entity_correct,
            intent_preserved=asr.intent_preserved,
        )
        for asr, sample, noise_name in result[: page.limit]
    ]
    more = len(result) > page.limit
    return Page(items=items, next_cursor=_offset_cursor(offset + page.limit) if more else None)


def _public_aggregates(row: DialectReports) -> dict[str, dict[str, dict[str, EngineAggregate]]]:
    raw = cast(dict[str, Any], row.aggregates)
    return {
        dialect: {
            cond: {eng: EngineAggregate.model_validate(agg) for eng, agg in engines.items()}
            for cond, engines in conds.items()
        }
        for dialect, conds in raw.items()
        if not dialect.startswith("_")
    }


@router.get(
    "/dialect-reports/{report_id}",
    responses=errors(404),
    summary="Poll progress; aggregates are filled when done",
)
async def get_dialect_report(report_id: UUID, key: ReadKey, session: Db) -> DialectReportOut:
    row = await _project_report(session, report_id, key.project_id)
    done = _complete(row)
    return DialectReportOut(
        id=row.id,
        dataset_id=row.dataset_id,
        progress=await _progress(session, row),
        aggregates=_public_aggregates(row) if done else {},
        top_errors=[TopError.model_validate(t) for t in row.top_errors] if done else [],
        bias_suggestions=list(row.bias_suggestions) if done else [],
        html=f"/api/v1/dialect-reports/{row.id}/html" if done else None,
        created_at=row.created_at,
    )


@router.get(
    "/dialect-reports/{report_id}/html",
    response_class=Response,
    responses={**binary_response("text/html", "Standalone HTML report"), **errors(404)},
)
async def get_dialect_report_html(report_id: UUID, key: ReadKey, session: Db) -> Response:
    row = await _project_report(session, report_id, key.project_id)
    if not _complete(row):
        raise ApiError(404, "not_found", "The report is not finished yet", {"id": str(report_id)})
    path = data_dir() / row.html_path if row.html_path else None
    if path is not None and path.exists():
        body = path.read_text(encoding="utf-8")
    else:  # the file lives on the worker's volume: rebuild the page from the stored aggregates
        dataset = await session.get(DialectDatasets, row.dataset_id)
        names = dict(
            (
                await session.execute(
                    select(NoiseProfiles.id, NoiseProfiles.name).where(
                        NoiseProfiles.id.in_(row.conditions)
                    )
                )
            ).all()
        )
        raw: dict[str, Any] = {k: v for k, v in row.aggregates.items() if not k.startswith("_")}
        body = render_html(
            dataset_name=dataset.name if dataset else "",
            created_at=row.created_at,
            conditions=[names[c] for c in row.conditions if c in names],
            engines=list(row.engines),
            aggregates=raw,
            top_errors_=row.top_errors,
            bias=list(row.bias_suggestions),
        )
    return Response(content=body, media_type="text/html; charset=utf-8")
