"""Inbound webhooks (docs/06-api-spec.md section 8). No API key: HMAC-signed instead."""

from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pareeksha.api.deps import Db, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.routers.audits import _clean_languages
from pareeksha.api.routers.integrations import _stored_secrets
from pareeksha.db.models import Agents, Calls, ExternalRefs, Integrations
from pareeksha.events.outbox import enqueue_session
from pareeksha.events.schemas import AuditRequested, make_envelope
from pareeksha.integrations.base import AuditRequest, ConnectorPermanentError, InboundRequest
from pareeksha.integrations.registry import UnknownConnectorError, get_registry
from pareeksha.integrations.signing import SignatureError, StaleTimestampError, verify_signature
from pareeksha.integrations.webhook import InboundRejectedError
from pareeksha.schemas.common import ErrorResponse
from pareeksha.schemas.integrations import InboundAccepted, InboundCallPayload

router = APIRouter(tags=["webhooks"])

SIGNING_SECRET = "signing_secret"
PREVIOUS_SIGNING_SECRET = "previous_signing_secret"


async def _source_integration(session: Db, integration_id: UUID) -> Integrations:
    row = await session.get(Integrations, integration_id)
    if row is None or not row.enabled:
        raise ApiError(404, "not_found", "Integration not found")
    try:
        direction = get_registry().get(row.connector).direction
    except UnknownConnectorError:
        direction = None
    if direction not in ("source", "both"):
        raise ApiError(404, "not_found", "Integration not found")
    return row


def _verify(row: Integrations, headers: dict[str, str], body: bytes) -> None:
    stored = _stored_secrets(row)
    active = [stored[k] for k in (SIGNING_SECRET, PREVIOUS_SIGNING_SECRET) if stored.get(k)]
    if not active:
        raise ApiError(401, "invalid_signature", "Invalid signature")
    try:
        verify_signature(headers, body, active)
    except StaleTimestampError as exc:
        raise ApiError(
            408, "timestamp_out_of_window", "Timestamp outside the 5 minute window"
        ) from exc
    except SignatureError as exc:
        raise ApiError(401, "invalid_signature", "Invalid signature") from exc


async def _agent_id(session: Db, row: Integrations, request: AuditRequest) -> uuid.UUID:
    if request.agent_name:
        found = await session.scalar(
            select(Agents.id).where(
                Agents.project_id == row.project_id, Agents.name == request.agent_name
            )
        )
        if found is not None:
            return found
    if request.agent_id:
        try:
            default = uuid.UUID(request.agent_id)
        except ValueError:
            default = None
        if default is not None and await session.scalar(
            select(Agents.id).where(Agents.project_id == row.project_id, Agents.id == default)
        ):
            return default
    raise ApiError(
        422,
        "unknown_agent",
        "agent_name matches no agent of this project and the integration has no default_agent_id",
        {"agent_name": request.agent_name},
    )


async def _existing_call(session: Db, integration_id: UUID, external_id: str) -> uuid.UUID | None:
    return await session.scalar(
        select(ExternalRefs.call_id).where(
            ExternalRefs.integration_id == integration_id,
            ExternalRefs.external_id == external_id,
        )
    )


@router.post(
    "/webhooks/inbound/{integration_id}",
    status_code=202,
    responses={
        **errors(400, 404, 408, 422),
        401: {
            "model": ErrorResponse,
            "description": "invalid_signature: bad HMAC (or missing signature headers)",
        },
    },
    summary="Receive a call recording from a source (HMAC-signed, deduped by external_id)",
    description=(
        "Headers `X-Pareeksha-Timestamp` and `X-Pareeksha-Signature: v1=<hex hmac_sha256(secret, "
        '"{ts}.{raw_body}")>`. Timestamps older than 5 minutes are rejected (408). The recording '
        "URL must be https and resolve to a public address (422 unsafe_url)."
    ),
)
async def receive_inbound_webhook(
    integration_id: UUID,
    body: InboundCallPayload,
    request: Request,
    session: Db,
    x_pareeksha_timestamp: Annotated[str, Header(alias="X-Pareeksha-Timestamp")],
    x_pareeksha_signature: Annotated[str, Header(alias="X-Pareeksha-Signature")],
) -> InboundAccepted:
    row = await _source_integration(session, integration_id)
    raw = await request.body()
    _verify(
        row,
        {
            "X-Pareeksha-Timestamp": x_pareeksha_timestamp,
            "X-Pareeksha-Signature": x_pareeksha_signature,
        },
        raw,
    )

    duplicate = await _existing_call(session, integration_id, body.external_id)
    if duplicate is not None:  # a replayed delivery: nothing is created, nothing is fetched
        return InboundAccepted(call_id=duplicate, duplicate=True)

    connector_cls = get_registry().get(row.connector)
    try:
        config = connector_cls.config_schema.model_validate(row.config)
        secret_values = connector_cls.secrets_schema.model_validate(_stored_secrets(row))
        requests = await connector_cls().ingest(
            InboundRequest(
                headers={"x-pareeksha-timestamp": x_pareeksha_timestamp},
                body=raw,
                integration_id=str(integration_id),
            ),
            config,
            secret_values,
        )
    except InboundRejectedError as exc:
        status = 422 if exc.code == "unsafe_url" else 400
        raise ApiError(status, exc.code, str(exc), {"external_id": body.external_id}) from exc
    except (ValidationError, ConnectorPermanentError) as exc:
        raise ApiError(400, "validation_error", f"integration is misconfigured: {exc}") from exc
    if len(requests) != 1:
        raise ApiError(400, "validation_error", "expected exactly one call per delivery")
    audit = requests[0]
    languages = _clean_languages(audit.language)
    agent_id = await _agent_id(session, row, audit)

    call_id = uuid.uuid4()
    try:
        async with session.begin_nested():  # a lost race on external_id rolls back only this
            session.add(
                Calls(
                    id=call_id,
                    project_id=row.project_id,
                    agent_id=agent_id,
                    source="import",
                    language=languages,
                    status="transcribing",
                    metadata_=dict(audit.metadata),
                )
            )
            await session.flush()
            session.add(
                ExternalRefs(
                    integration_id=integration_id, external_id=audit.external_id, call_id=call_id
                )
            )
            await session.flush()
    except IntegrityError:
        winner = await _existing_call(session, integration_id, audit.external_id)
        if winner is None:
            raise
        return InboundAccepted(call_id=winner, duplicate=True)

    enqueue_session(
        session,
        make_envelope(
            AuditRequested(
                call_id=call_id,
                source="import",
                agent_id=agent_id,
                language=languages,
                recording_ref=audit.recording_url,
                integration_id=integration_id,
                external_id=audit.external_id,
            ),
            producer="api",
            correlation_id=str(call_id),
        ),
    )
    return InboundAccepted(call_id=call_id, duplicate=False)
