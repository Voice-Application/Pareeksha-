"""Example connector: a Slack sink that posts failed calls to an incoming webhook.

One file: config/secrets schemas, the Connector subclass, nothing else. Register it with the
`pareeksha.connectors` entry point in pyproject.toml.
"""

from __future__ import annotations

from typing import ClassVar

import httpx
from pydantic import BaseModel, Field

from pareeksha.integrations.base import (
    Connector,
    ConnectorDirection,
    ConnectorPermanentError,
    ConnectorRetryableError,
    DeliveryCtx,
    DeliveryOutcome,
    TestResult,
)


class SlackConfig(BaseModel):
    only_critical: bool = Field(default=True, description="post only critical failures")
    timeout_s: float = Field(default=10.0, gt=0, le=60)


class SlackSecrets(BaseModel):
    webhook_url: str = Field(description="Slack incoming-webhook URL (https://hooks.slack.com/...)")


class SlackConnector(Connector):
    name: ClassVar[str] = "slack"
    direction: ClassVar[ConnectorDirection] = "sink"
    config_schema: ClassVar[type[BaseModel]] = SlackConfig
    secrets_schema: ClassVar[type[BaseModel]] = SlackSecrets
    subscribes_to: ClassVar[list[str]] = ["evaluation.completed"]

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # tests inject httpx.MockTransport

    async def test(self, config: BaseModel, secrets: BaseModel) -> TestResult:
        sec = SlackSecrets.model_validate(secrets.model_dump())
        if not sec.webhook_url.startswith("https://"):
            return TestResult(ok=False, detail="webhook_url must be https")
        return TestResult(ok=True, detail="webhook_url looks valid (no message sent)")

    async def handle(self, event, config, secrets, ctx: DeliveryCtx) -> DeliveryOutcome:  # type: ignore[no-untyped-def]
        cfg, sec = SlackConfig.model_validate(config.model_dump()), SlackSecrets.model_validate(
            secrets.model_dump()
        )
        s = ctx.summary
        if s is None:
            return DeliveryOutcome(status="skipped", detail="not an evaluation event")
        if s.passed or (cfg.only_critical and not s.critical_failure):
            return DeliveryOutcome(status="skipped", detail="call did not need an alert")
        text = (
            f":rotating_light: *{s.agent_name or 'agent'}* scored {s.overall_score}/100"
            f" ({', '.join(s.failure_types) or 'no failure types'})\n{s.summary}\n<{s.link}|Open call>"
        )
        async with httpx.AsyncClient(transport=self._transport, timeout=cfg.timeout_s) as client:
            try:
                resp = await client.post(sec.webhook_url, json={"text": text})
            except httpx.TransportError as exc:
                raise ConnectorRetryableError(f"slack unreachable: {exc}") from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            retry = resp.headers.get("Retry-After")
            raise ConnectorRetryableError(
                f"slack answered {resp.status_code}", retry_after_s=float(retry) if retry else None
            )
        if resp.status_code >= 400:
            raise ConnectorPermanentError(f"slack answered {resp.status_code}: {resp.text[:200]}")
        return DeliveryOutcome(status="succeeded", http_status=resp.status_code)
