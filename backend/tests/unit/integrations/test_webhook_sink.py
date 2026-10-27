"""INT-01: registry discovery, webhook sink and idempotent delivery log."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from importlib.metadata import EntryPoint
from typing import ClassVar

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import BaseModel

from pareeksha.api.auth import authenticate
from pareeksha.api.main import app
from pareeksha.events.schemas import (
    AnyEnvelope,
    EvaluationCompleted,
    RunCompleted,
    RunCompletedSummary,
    make_envelope,
)
from pareeksha.integrations.base import (
    AuditRequest,
    Connector,
    ConnectorPermanentError,
    ConnectorRetryableError,
    DeliveryCtx,
    EvaluationSummary,
    InboundRequest,
    TestResult,
)
from pareeksha.integrations.crypto import SecretBox
from pareeksha.integrations.delivery import (
    DeliveryService,
    InMemoryDeliveryStore,
    IntegrationRecord,
)
from pareeksha.integrations.registry import ConnectorRegistry, UnknownConnectorError, get_registry
from pareeksha.integrations.signing import verify_signature
from pareeksha.integrations.webhook import WebhookConfig, WebhookConnector, WebhookSecrets

SECRET = "0123456789abcdef-signing"
PUBLIC = "93.184.216.34"


class Bad(Connector):  # abstract: test() missing, bad name
    name: ClassVar[str] = "Bad Name"


class Good(Connector):
    name: ClassVar[str] = "good"
    direction: ClassVar = "source"
    config_schema: ClassVar = BaseModel
    secrets_schema: ClassVar = BaseModel
    subscribes_to: ClassVar = []

    async def test(self, config: BaseModel, secrets: BaseModel) -> TestResult:
        raise NotImplementedError

    async def ingest(
        self, request: InboundRequest, config: BaseModel, secrets: BaseModel
    ) -> list[AuditRequest]:
        return []


def test_registry_discovers_builtin_from_installed_entry_points() -> None:
    registry = ConnectorRegistry.from_entry_points()
    assert "webhook" in registry.names()
    assert registry.rejected == {}
    assert registry.get("webhook") is WebhookConnector


def test_registry_loads_entry_point_objects_and_refuses_broken_ones() -> None:
    eps = [
        EntryPoint("good", f"{__name__}:Good", "pareeksha.connectors"),
        EntryPoint("bad", f"{__name__}:Bad", "pareeksha.connectors"),
        EntryPoint("missing", "no_such_pkg_xyz:Thing", "pareeksha.connectors"),
        EntryPoint("dup", f"{__name__}:Good", "pareeksha.connectors"),
    ]
    registry = ConnectorRegistry.from_entry_points(eps)
    assert registry.names() == ["good"]
    assert set(registry.rejected) == {"bad", "missing", "dup"}
    assert "import failed" in registry.rejected["missing"][0]
    assert any("duplicate" in p for p in registry.rejected["dup"])
    with pytest.raises(UnknownConnectorError):
        registry.get("nope")


def test_connectors_endpoint_lists_schemas() -> None:
    get_registry()
    # API-01's key check is DB-backed (covered in tests/db); this test is about the payload.
    app.dependency_overrides[authenticate] = lambda: None
    try:
        client = TestClient(app)
        resp = client.get(
            "/api/v1/integrations/connectors", headers={"Authorization": "Bearer pk_x"}
        )
    finally:
        app.dependency_overrides.pop(authenticate, None)
    assert resp.status_code == 200
    webhook = next(c for c in resp.json() if c["name"] == "webhook")
    assert webhook["direction"] == "sink"
    assert "signing_secret" in webhook["secrets_schema"]["properties"]


async def _public(host: str, port: int) -> list[str]:
    return [PUBLIC]


async def _private(host: str, port: int) -> list[str]:
    return ["10.1.2.3"]


def make_connector(handler: Callable[[httpx.Request], httpx.Response]) -> WebhookConnector:
    return WebhookConnector(resolver=_public, transport=httpx.MockTransport(handler))


def evaluation(passed: bool = False) -> tuple[AnyEnvelope, EvaluationSummary]:
    call_id = uuid.uuid4()
    env = make_envelope(
        EvaluationCompleted(
            call_id=call_id,
            evaluation_id=uuid.uuid4(),
            overall_score=40.0,
            passed=passed,
            failure_types=["wrong_fact"],
        ),
        producer="t",
        correlation_id=str(call_id),
    )
    summary = EvaluationSummary(
        call_id=call_id,
        agent_id=uuid.uuid4(),
        agent_name="EMI Reminder Bot",
        source="import",
        external_id="exotel-CA123",
        overall_score=40.0,
        passed=passed,
        failure_types=["wrong_fact"],
        summary="Misheard 4,000 as 40,000.",
        link="https://pareeksha.example.com/calls/x",
        metadata={"phone": "+91XXXXXXXX00"},
    )
    return env, summary


def service_and_record(**cfg: object) -> tuple[DeliveryService, IntegrationRecord]:
    box = SecretBox(Fernet.generate_key())
    record = IntegrationRecord(
        id=uuid.uuid4(),
        connector="webhook",
        config={"url": "https://hooks.example.com/in", **cfg},
        secrets_encrypted=box.encrypt({"signing_secret": SECRET}),
    )
    return DeliveryService(InMemoryDeliveryStore(), box), record


async def test_sink_posts_signed_payload_and_logs_delivery() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, text="ok")

    service, record = service_and_record()
    env, summary = evaluation()
    row = await service.deliver(make_connector(handler), record, env, summary=summary)
    assert row.status == "succeeded" and row.http_status == 200 and row.attempts == 1
    (req,) = captured
    verify_signature(dict(req.headers), req.content, SECRET)
    body = json.loads(req.content)
    assert body["type"] == "evaluation.completed"
    assert body["event_id"] == str(env.event_id)
    assert body["data"]["agent"]["name"] == "EMI Reminder Bot"
    assert body["data"]["metadata"] == {"phone": "+91XXXXXXXX00"}
    assert "transcript" not in req.content.decode()
    assert (await service.store.recent(record.id))[0].id == row.id


async def test_delivery_is_idempotent_per_integration_and_event() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    service, record = service_and_record()
    env, summary = evaluation()
    connector = make_connector(handler)
    first = await service.deliver(connector, record, env, summary=summary)
    again = await service.deliver(connector, record, env, summary=summary)
    assert calls == 1 and first.id == again.id and again.attempts == 1
    other = IntegrationRecord(uuid.uuid4(), "webhook", record.config, record.secrets_encrypted)
    await service.deliver(connector, other, env, summary=summary)
    assert calls == 2


async def test_only_failed_skips_passing_calls_and_unsubscribed_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no request expected")

    service, record = service_and_record(only_failed=True)
    env, summary = evaluation(passed=True)
    row = await service.deliver(make_connector(handler), record, env, summary=summary)
    assert row.status == "skipped"

    run_env = make_envelope(
        RunCompleted(
            run_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            kind="matrix",
            status="completed",
            summary=RunCompletedSummary(item_count=1, evaluated_count=1, error_count=0),
        ),
        producer="t",
        correlation_id="r",
    )
    row = await service.deliver(make_connector(handler), record, run_env)
    assert row.status == "skipped" and "not subscribed" in (row.response_excerpt or "")


async def test_run_completed_payload_when_subscribed() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(202)

    service, record = service_and_record(events=["run.completed"])
    run_env = make_envelope(
        RunCompleted(
            run_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            kind="matrix",
            status="completed",
            summary=RunCompletedSummary(item_count=2, evaluated_count=2, error_count=0),
        ),
        producer="t",
        correlation_id="r",
    )
    row = await service.deliver(make_connector(handler), record, run_env)
    assert row.status == "succeeded"
    assert json.loads(captured[0].content)["data"]["summary"]["item_count"] == 2


async def test_retryable_then_success_counts_attempts() -> None:
    responses = iter([503, 429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(responses)
        return httpx.Response(status, headers={"retry-after": "7"} if status == 429 else {})

    service, record = service_and_record()
    env, summary = evaluation()
    connector = make_connector(handler)
    with pytest.raises(ConnectorRetryableError):
        await service.deliver(connector, record, env, summary=summary)
    with pytest.raises(ConnectorRetryableError) as info:
        await service.deliver(connector, record, env, summary=summary)
    assert info.value.retry_after_s == 7.0
    row = await service.deliver(connector, record, env, summary=summary)
    assert row.status == "succeeded" and row.attempts == 3


async def test_permanent_failure_recorded_not_raised() -> None:
    service, record = service_and_record()
    env, summary = evaluation()
    row = await service.deliver(
        make_connector(lambda r: httpx.Response(401, text="nope")),
        record,
        env,
        summary=summary,
    )
    assert row.status == "failed" and "401" in (row.response_excerpt or "")


async def test_bad_config_and_wrong_key_fail_without_calling_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request expected")

    env, summary = evaluation()
    service, record = service_and_record()
    bad = IntegrationRecord(
        record.id, "webhook", {"url": "http://insecure"}, record.secrets_encrypted
    )
    row = await service.deliver(make_connector(handler), bad, env, summary=summary)
    assert row.status == "failed"
    other_box = DeliveryService(InMemoryDeliveryStore(), SecretBox(Fernet.generate_key()))
    row = await other_box.deliver(make_connector(handler), record, env, summary=summary)
    assert row.status == "failed" and "cannot decrypt" in (row.response_excerpt or "")


async def test_ssrf_blocked_target_is_permanent_failure() -> None:

    service, record = service_and_record()
    env, summary = evaluation()
    row = await service.deliver(WebhookConnector(resolver=_private), record, env, summary=summary)
    assert row.status == "failed" and "blocked" in (row.response_excerpt or "")


async def test_timeout_and_transport_errors_are_retryable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    service, record = service_and_record()
    env, summary = evaluation()
    for h in (timeout, refused):
        with pytest.raises(ConnectorRetryableError):
            await service.deliver(make_connector(h), record, env, summary=summary)


async def test_connector_test_method_and_rotation_header() -> None:
    seen: list[httpx.Request] = []

    def ok(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    cfg = WebhookConfig(url="https://hooks.example.com/in")
    sec = WebhookSecrets(signing_secret=SECRET, previous_signing_secret="previous-secret-value")
    assert (await make_connector(ok).test(cfg, sec)).ok
    assert seen[0].headers["x-pareeksha-signature"].count("v1=") == 2
    assert not (await make_connector(lambda r: httpx.Response(500)).test(cfg, sec)).ok

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x")

    assert "transport" in (await make_connector(boom).test(cfg, sec)).detail

    result = await WebhookConnector(resolver=_private).test(cfg, sec)
    assert not result.ok and "blocked" in result.detail


async def test_wrong_typed_config_rejected_and_source_methods_refused() -> None:
    connector = WebhookConnector()
    ctx = DeliveryCtx(integration_id=uuid.uuid4(), delivery_id=uuid.uuid4(), attempt=1)
    env, _ = evaluation()
    with pytest.raises(ConnectorPermanentError):
        await connector.handle(
            env, WebhookSecrets(signing_secret=SECRET), WebhookConfig(url="https://a.example"), ctx
        )


def test_webhook_config_requires_https() -> None:
    with pytest.raises(ValueError, match="https"):
        WebhookConfig(url="http://x.example/")
