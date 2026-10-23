"""Inbound webhooks (docs/06-api-spec.md section 8). No API key: HMAC-signed instead."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header

from pareeksha.api.deps import errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.common import ErrorResponse
from pareeksha.schemas.integrations import InboundAccepted, InboundCallPayload

router = APIRouter(tags=["webhooks"])


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
    x_pareeksha_timestamp: Annotated[str, Header(alias="X-Pareeksha-Timestamp")],
    x_pareeksha_signature: Annotated[str, Header(alias="X-Pareeksha-Signature")],
) -> InboundAccepted:
    # STUB(INT-03)
    not_implemented("INT-03")
