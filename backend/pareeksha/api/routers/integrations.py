"""Integrations (docs/06-api-spec.md section 8)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.integrations.registry import get_registry
from pareeksha.schemas.common import Page
from pareeksha.schemas.integrations import (
    ConnectorInfo,
    DeliveryOut,
    DeliveryStatus,
    IntegrationCreate,
    IntegrationOut,
    IntegrationTestResult,
    IntegrationUpdate,
)

router = APIRouter(tags=["integrations"], responses=AUTH_ERRORS)


@router.get(
    "/integrations/connectors",
    dependencies=[scoped("read")],
    summary="Installed connectors (built-in and entry-point plugins) with JSON Schemas",
)
async def list_connectors() -> list[ConnectorInfo]:
    return get_registry().info()


@router.post(
    "/integrations",
    status_code=201,
    dependencies=[scoped("admin")],
    responses=errors(409),
    summary="Create an integration; secrets are write-only (webhook: signing_secret shown once)",
)
async def create_integration(body: IntegrationCreate) -> IntegrationOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.get("/integrations", dependencies=[scoped("read")])
async def list_integrations(page: Pagination) -> Page[IntegrationOut]:
    # STUB(API-02)
    not_implemented("API-02")


@router.get("/integrations/{integration_id}", dependencies=[scoped("read")], responses=errors(404))
async def get_integration(integration_id: UUID) -> IntegrationOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.patch(
    "/integrations/{integration_id}",
    dependencies=[scoped("admin")],
    responses=errors(404, 409),
    summary="Update; secrets are replaced only if provided",
)
async def update_integration(integration_id: UUID, body: IntegrationUpdate) -> IntegrationOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.delete(
    "/integrations/{integration_id}",
    status_code=204,
    dependencies=[scoped("admin")],
    responses=errors(404),
)
async def delete_integration(integration_id: UUID) -> Response:
    # STUB(API-02)
    not_implemented("API-02")


@router.post(
    "/integrations/{integration_id}/test",
    dependencies=[scoped("admin")],
    responses=errors(404),
    summary="Run the connector's test() and store the result",
)
async def test_integration(integration_id: UUID) -> IntegrationTestResult:
    # STUB(INT-01)
    not_implemented("INT-01")


@router.get(
    "/integrations/{integration_id}/deliveries",
    dependencies=[scoped("read")],
    responses=errors(404),
    summary="Delivery log",
)
async def list_integration_deliveries(
    integration_id: UUID, page: Pagination, status: DeliveryStatus | None = None
) -> Page[DeliveryOut]:
    # STUB(INT-01)
    not_implemented("INT-01")


@router.post(
    "/integrations/{integration_id}/deliveries/{delivery_id}/redeliver",
    status_code=202,
    dependencies=[scoped("admin")],
    responses=errors(404),
)
async def redeliver_integration_delivery(integration_id: UUID, delivery_id: UUID) -> DeliveryOut:
    # STUB(INT-01)
    not_implemented("INT-01")
