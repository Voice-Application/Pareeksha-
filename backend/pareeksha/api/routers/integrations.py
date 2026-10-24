"""Integrations (docs/06-api-spec.md section 8)."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Response

from pareeksha.api.auth import AdminKey, ReadKey, scoped
from pareeksha.api.connectors import connector_direction
from pareeksha.api.crud import delete_row, flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.stubs import not_implemented
from pareeksha.db.models import Integrations
from pareeksha.integrations.crypto import SecretBox, SecretDecryptError
from pareeksha.integrations.registry import get_registry
from pareeksha.schemas.common import Page
from pareeksha.schemas.integrations import (
    ConnectorInfo,
    DeliveryOut,
    DeliveryStatus,
    EventFilter,
    IntegrationCreate,
    IntegrationOut,
    IntegrationTestResult,
    IntegrationUpdate,
)

router = APIRouter(tags=["integrations"], responses=AUTH_ERRORS)

_DUPLICATE = "An integration with this name already exists"
WEBHOOK = "webhook"
SIGNING_SECRET = "signing_secret"


def _secret_box() -> SecretBox:
    """The Fernet box for ``SECRET_KEY``; a server misconfiguration is a 500, not a client error."""
    key = os.environ.get("SECRET_KEY")
    if not key:
        raise ApiError(500, "internal_error", "SECRET_KEY is not configured on the server")
    try:
        return SecretBox(key)
    except ValueError as exc:
        raise ApiError(500, "internal_error", str(exc)) from exc


def _stored_secrets(row: Integrations) -> dict[str, str]:
    if not row.secrets_encrypted:
        return {}
    try:
        return _secret_box().decrypt(row.secrets_encrypted.decode())
    except SecretDecryptError as exc:
        raise ApiError(500, "internal_error", str(exc)) from exc


def _inbound_url(row: Integrations) -> str | None:
    if row.connector != WEBHOOK:
        return None
    base = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/api/v1/webhooks/inbound/{row.id}"


def _out(row: Integrations, *, signing_secret: str | None = None) -> IntegrationOut:
    """Secrets are write-only: only ``secrets_set`` is shown (webhook secret once, on create)."""
    return IntegrationOut(
        id=row.id,
        connector=row.connector,
        name=row.name,
        direction=row.direction,  # type: ignore[arg-type]
        enabled=row.enabled,
        config=dict(row.config),  # type: ignore[call-overload]
        secrets_set=bool(row.secrets_encrypted),
        event_filter=EventFilter.model_validate(row.event_filter or {}),
        last_test_at=row.last_test_at,
        last_test_ok=row.last_test_ok,
        created_at=row.created_at,
        updated_at=row.updated_at,
        inbound_url=_inbound_url(row),
        signing_secret=signing_secret,
    )


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
    responses=errors(409),
    summary="Create an integration; secrets are write-only (webhook: signing_secret shown once)",
)
async def create_integration(body: IntegrationCreate, key: AdminKey, session: Db) -> IntegrationOut:
    direction = connector_direction(body.connector)
    if direction is None:
        raise ApiError(
            400,
            "validation_error",
            f"Unknown connector {body.connector!r}",
            {"connector": body.connector},
        )
    secret_values = dict(body.secrets)
    signing_secret: str | None = None
    if body.connector == WEBHOOK:
        signing_secret = secret_values.setdefault(SIGNING_SECRET, secrets.token_urlsafe(32))
    row = Integrations(
        project_id=key.project_id,
        connector=body.connector,
        name=body.name,
        direction=direction,
        enabled=body.enabled,
        config=body.config,
        secrets_encrypted=_secret_box().encrypt(secret_values).encode() if secret_values else None,
        event_filter=body.event_filter.model_dump(mode="json"),
    )
    session.add(row)
    await flush(session, _DUPLICATE, refresh=row)
    return _out(row, signing_secret=signing_secret)


@router.get("/integrations")
async def list_integrations(key: ReadKey, session: Db, page: Pagination) -> Page[IntegrationOut]:
    rows, next_cursor = await paginate(
        session, Integrations, [Integrations.project_id == key.project_id], page
    )
    return Page(items=[_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/integrations/{integration_id}", responses=errors(404))
async def get_integration(integration_id: UUID, key: ReadKey, session: Db) -> IntegrationOut:
    row = await get_or_404(session, Integrations, integration_id, key.project_id, "Integration")
    return _out(row)


@router.patch(
    "/integrations/{integration_id}",
    responses=errors(404, 409),
    summary="Update; secrets are replaced only if provided",
)
async def update_integration(
    integration_id: UUID, body: IntegrationUpdate, key: AdminKey, session: Db
) -> IntegrationOut:
    row = await get_or_404(session, Integrations, integration_id, key.project_id, "Integration")
    if body.name is not None:
        row.name = body.name
    if body.config is not None:
        row.config = body.config
    if body.event_filter is not None:
        row.event_filter = body.event_filter.model_dump(mode="json")
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.secrets is not None:
        replacement = dict(body.secrets)
        if row.connector == WEBHOOK:  # rotating other secrets must not lose the signing secret
            kept = _stored_secrets(row).get(SIGNING_SECRET)
            if kept is not None:
                replacement.setdefault(SIGNING_SECRET, kept)
        row.secrets_encrypted = _secret_box().encrypt(replacement).encode() if replacement else None
    row.updated_at = datetime.now(UTC)
    await flush(session, _DUPLICATE, refresh=row)
    return _out(row)


@router.delete(
    "/integrations/{integration_id}",
    status_code=204,
    responses=errors(404),
)
async def delete_integration(integration_id: UUID, key: AdminKey, session: Db) -> Response:
    row = await get_or_404(session, Integrations, integration_id, key.project_id, "Integration")
    await delete_row(session, Integrations, row.id, "Integration is in use")
    return Response(status_code=204)


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
