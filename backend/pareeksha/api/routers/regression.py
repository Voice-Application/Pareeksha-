"""Regression runs (docs/06-api-spec.md section 3). Promotion lives in ``calls.py``."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.common import Page
from pareeksha.schemas.regression import RegressionTestOut, RegressionTestUpdate
from pareeksha.schemas.runs import RegressionRunCreate, RegressionStatus, RunCreated

router = APIRouter(tags=["regression"], responses=AUTH_ERRORS)


@router.post(
    "/runs:regression",
    status_code=201,
    dependencies=[scoped("runs:write")],
    responses=errors(402, 404),
    summary="Run the agent's regression tests with the given statuses (default: blocking)",
)
async def create_regression_run(body: RegressionRunCreate) -> RunCreated:
    # STUB(API-05)
    not_implemented("API-05")


@router.get(
    "/regression-tests",
    dependencies=[scoped("read")],
    summary="List regression tests with their last result",
)
async def list_regression_tests(
    page: Pagination, agent_id: UUID | None = None, status: RegressionStatus | None = None
) -> Page[RegressionTestOut]:
    # STUB(API-05)
    not_implemented("API-05")


@router.patch(
    "/regression-tests/{regression_test_id}",
    dependencies=[scoped("runs:write")],
    responses=errors(404),
    summary="Change status (blocking/scheduled/manual/retired), baseline, tolerance or notes",
)
async def update_regression_test(
    regression_test_id: UUID, body: RegressionTestUpdate
) -> RegressionTestOut:
    # STUB(API-05)
    not_implemented("API-05")
