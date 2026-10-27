import asyncio
import uuid

import httpx
import pytest
from pareeksha.integrations.base import (
    ConnectorRetryableError,
    DeliveryCtx,
    EvaluationSummary,
    validate_connector_class,
)

from pareeksha_connector_slack import SlackConfig, SlackConnector, SlackSecrets


def _ctx(passed: bool, critical: bool) -> DeliveryCtx:
    summary = EvaluationSummary(
        call_id=uuid.uuid4(), source="import", overall_score=40, passed=passed,
        critical_failure=critical, failure_types=["wrong_fact"], summary="Misheard the amount.",
        link="http://localhost:3000/calls/1",
    )
    return DeliveryCtx(integration_id=uuid.uuid4(), delivery_id=uuid.uuid4(), attempt=1, summary=summary)


def _run(handler, ctx):
    connector = SlackConnector(transport=httpx.MockTransport(handler))
    secrets = SlackSecrets(webhook_url="https://hooks.slack.com/services/T/B/x")
    return asyncio.run(connector.handle(None, SlackConfig(), secrets, ctx))


def test_contract_is_valid():
    assert validate_connector_class(SlackConnector) == []


def test_critical_failure_is_posted():
    seen = []
    out = _run(lambda r: seen.append(r) or httpx.Response(200, text="ok"), _ctx(False, True))
    assert out.status == "succeeded" and "Misheard" in seen[0].content.decode()


def test_passing_call_is_skipped():
    out = _run(lambda r: httpx.Response(500), _ctx(True, False))
    assert out.status == "skipped"


def test_slack_5xx_is_retryable():
    with pytest.raises(ConnectorRetryableError):
        _run(lambda r: httpx.Response(503), _ctx(False, True))
