"""Generic Webhook connector, source and sink (docs/10 section 2.1).

Sink: one signed POST per matching event. ``include_transcript`` is deliberately not offered: sinks
receive an ``EvaluationSummary`` which carries no transcript or audio (data minimisation).
"""

from __future__ import annotations

import json
import logging
from typing import ClassVar

import httpx
from pydantic import BaseModel, Field, field_validator

from pareeksha.events.schemas import AnyEnvelope
from pareeksha.integrations.base import (
    AuditRequest,
    Connector,
    ConnectorDirection,
    ConnectorPermanentError,
    ConnectorRetryableError,
    DeliveryCtx,
    DeliveryOutcome,
    InboundRequest,
    TestResult,
)
from pareeksha.integrations.signing import sign_headers
from pareeksha.integrations.ssrf import (
    DEV_ALLOW_PRIVATE_ENV,
    Resolver,
    SSRFError,
    dev_allow_private,
    resolve_public,
    safe_request,
    system_resolver,
)
from pareeksha.schemas.integrations import InboundCallPayload

log = logging.getLogger(__name__)

EVENT_ID_HEADER = "X-Pareeksha-Event-Id"


class WebhookConfig(BaseModel):
    url: str = Field(description="https endpoint that receives the events")
    events: list[str] = Field(default_factory=lambda: ["evaluation.completed"])
    only_failed: bool = False
    timeout_s: float = Field(default=10.0, gt=0, le=60)
    #: Source side: agent that imported calls are audited against when the payload's
    #: ``agent_name`` matches no agent of the project.
    default_agent_id: str | None = None

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("url must start with https://")
        return value


class WebhookSecrets(BaseModel):
    signing_secret: str = Field(min_length=16)
    #: optional previous secret during rotation; both signatures are sent
    previous_signing_secret: str | None = None


class InboundRejectedError(ConnectorPermanentError):
    """An inbound delivery that cannot become a call: ``code`` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WebhookConnector(Connector):
    name: ClassVar[str] = "webhook"
    direction: ClassVar[ConnectorDirection] = "both"
    config_schema: ClassVar[type[BaseModel]] = WebhookConfig
    secrets_schema: ClassVar[type[BaseModel]] = WebhookSecrets
    subscribes_to: ClassVar[list[str]] = ["evaluation.completed", "run.completed"]

    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        allow_private: bool | None = None,
    ) -> None:
        # injection points for tests; production uses DNS and the default transport
        self._resolver = resolver
        self._transport = transport
        if allow_private is None:
            allow_private = dev_allow_private()
        if allow_private:
            log.warning("%s is set: the SSRF public-address check is OFF", DEV_ALLOW_PRIVATE_ENV)
        self._allow_private = allow_private

    async def _post(
        self,
        cfg: WebhookConfig,
        sec: WebhookSecrets,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        secrets = [sec.signing_secret]
        if sec.previous_signing_secret:
            secrets.append(sec.previous_signing_secret)
        headers = {
            "Content-Type": "application/json",
            **(extra_headers or {}),
            **sign_headers(secrets, body),
        }
        try:
            return await safe_request(
                "POST",
                cfg.url,
                headers=headers,
                content=body,
                timeout_s=cfg.timeout_s,
                max_bytes=64 * 1024,
                resolver=self._resolver,
                transport=self._transport,
                allow_private=self._allow_private,
            )
        except SSRFError as exc:
            raise ConnectorPermanentError(f"blocked: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ConnectorRetryableError(f"timeout: {exc!r}") from exc
        except httpx.TransportError as exc:
            raise ConnectorRetryableError(f"transport error: {exc!r}") from exc

    async def test(self, config: BaseModel, secrets: BaseModel) -> TestResult:
        cfg, sec = _typed(config, secrets)
        body = json.dumps({"type": "ping"}).encode()
        try:
            response = await self._post(cfg, sec, body)
        except ConnectorPermanentError as exc:
            return TestResult(ok=False, detail=str(exc))
        except ConnectorRetryableError as exc:
            return TestResult(ok=False, detail=str(exc))
        ok = response.status_code < 400
        return TestResult(ok=ok, detail=f"HTTP {response.status_code}")

    async def ingest(
        self, request: InboundRequest, config: BaseModel, secrets: BaseModel
    ) -> list[AuditRequest]:
        """Signature is already verified; check the payload and the recording URL (SSRF guard)."""
        cfg, _ = _typed(config, secrets)
        try:
            payload = InboundCallPayload.model_validate_json(request.body)
        except ValueError as exc:
            raise InboundRejectedError(
                "validation_error", f"invalid inbound payload: {exc}"
            ) from exc
        try:
            await resolve_public(
                payload.recording_url, self._resolver, allow_private=self._allow_private
            )
        except SSRFError as exc:
            raise InboundRejectedError("unsafe_url", f"recording_url refused: {exc}") from exc
        return [
            AuditRequest(
                recording_url=payload.recording_url,
                agent_id=cfg.default_agent_id,
                agent_name=payload.agent_name,
                language=payload.language,
                external_id=payload.external_id,
                metadata=payload.metadata,
            )
        ]

    async def handle(
        self, event: AnyEnvelope, config: BaseModel, secrets: BaseModel, ctx: DeliveryCtx
    ) -> DeliveryOutcome:
        cfg, sec = _typed(config, secrets)
        event_type = event.type.value
        if event_type not in cfg.events:
            return DeliveryOutcome(status="skipped", detail=f"event {event_type} not subscribed")
        if ctx.summary is not None and cfg.only_failed and ctx.summary.passed is not False:
            return DeliveryOutcome(status="skipped", detail="only_failed and call did not fail")
        data = (
            ctx.summary.model_dump(mode="json", exclude={"agent_id", "agent_name"})
            if ctx.summary is not None
            else event.payload.model_dump(mode="json")
        )
        if ctx.summary is not None:
            data["agent"] = {
                "id": None if ctx.summary.agent_id is None else str(ctx.summary.agent_id),
                "name": ctx.summary.agent_name,
            }
        payload = {
            "event_id": str(event.event_id),
            "type": event_type,
            "occurred_at": event.occurred_at.isoformat(),
            "data": data,
        }
        body = json.dumps(payload, sort_keys=True).encode()
        # the event id is stable across retries and redeliveries: receivers dedupe on it
        response = await self._post(cfg, sec, body, {EVENT_ID_HEADER: str(event.event_id)})
        status = response.status_code
        excerpt = response.text[:2000]
        if status == 429 or status >= 500:
            retry_after = response.headers.get("retry-after", "")
            raise ConnectorRetryableError(
                f"HTTP {status}",
                retry_after_s=float(retry_after) if retry_after.isdigit() else None,
            )
        if status >= 400:
            raise ConnectorPermanentError(f"HTTP {status}: {excerpt[:200]}")
        return DeliveryOutcome(status="succeeded", http_status=status, response_excerpt=excerpt)


def _typed(config: BaseModel, secrets: BaseModel) -> tuple[WebhookConfig, WebhookSecrets]:
    if not isinstance(config, WebhookConfig) or not isinstance(secrets, WebhookSecrets):
        raise ConnectorPermanentError("webhook connector got config/secrets of the wrong type")
    return config, secrets
