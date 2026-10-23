"""Dialect datasets and reports (docs/06-api-spec.md section 5)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Response, UploadFile

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, binary_response, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.common import Page
from pareeksha.schemas.dialect import (
    ClipResultOut,
    DatasetCreate,
    DatasetOut,
    DialectEvaluateAccepted,
    DialectEvaluateRequest,
    DialectReportOut,
    DialectReportSummaryOut,
    SamplesUploadResult,
)

router = APIRouter(tags=["dialect"], responses=AUTH_ERRORS)


@router.post(
    "/dialect-datasets",
    status_code=201,
    dependencies=[scoped("runs:write")],
    responses=errors(409),
)
async def create_dialect_dataset(body: DatasetCreate) -> DatasetOut:
    # STUB(EVAL-05)
    not_implemented("EVAL-05")


@router.get("/dialect-datasets", dependencies=[scoped("read")], summary="List datasets")
async def list_dialect_datasets(page: Pagination) -> Page[DatasetOut]:
    # STUB(EVAL-05)
    not_implemented("EVAL-05")


@router.post(
    "/dialect-datasets/{dataset_id}/samples",
    dependencies=[scoped("runs:write")],
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
) -> SamplesUploadResult:
    # STUB(EVAL-05)
    not_implemented("EVAL-05")


@router.post(
    "/dialect-datasets/{dataset_id}/evaluate",
    status_code=202,
    dependencies=[scoped("runs:write")],
    responses=errors(404, 409),
    summary="Evaluate every clip under every noise condition",
)
async def evaluate_dialect_dataset(
    dataset_id: UUID, body: DialectEvaluateRequest
) -> DialectEvaluateAccepted:
    # STUB(EVAL-05)
    not_implemented("EVAL-05")


@router.get("/dialect-reports", dependencies=[scoped("read")], summary="List reports")
async def list_dialect_reports(
    page: Pagination, dataset_id: UUID | None = None
) -> Page[DialectReportSummaryOut]:
    # STUB(EVAL-05)
    not_implemented("EVAL-05")


@router.get(
    "/dialect-reports/{report_id}/clips",
    dependencies=[scoped("read")],
    responses=errors(404),
    summary="Worst clips first, for the heatmap drill-down",
)
async def list_dialect_report_clips(
    report_id: UUID,
    page: Pagination,
    dialect: str | None = None,
    condition: str | None = None,
    engine: str | None = None,
) -> Page[ClipResultOut]:
    # STUB(EVAL-05)
    not_implemented("EVAL-05")


@router.get(
    "/dialect-reports/{report_id}",
    dependencies=[scoped("read")],
    responses=errors(404),
    summary="Poll progress; aggregates are filled when done",
)
async def get_dialect_report(report_id: UUID) -> DialectReportOut:
    # STUB(EVAL-05)
    not_implemented("EVAL-05")


@router.get(
    "/dialect-reports/{report_id}/html",
    dependencies=[scoped("read")],
    response_class=Response,
    responses={**binary_response("text/html", "Standalone HTML report"), **errors(404)},
)
async def get_dialect_report_html(report_id: UUID) -> Response:
    # STUB(EVAL-05)
    not_implemented("EVAL-05")
