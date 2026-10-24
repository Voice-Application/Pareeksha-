"""INT-02: HubSpot sink against mocked HTTP (no live token; see proof/INT-02/proof.md)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet

from pareeksha.events.schemas import AnyEnvelope, EvaluationCompleted, make_envelope
from pareeksha.integrations.base import (
    ConnectorPermanentError,
    ConnectorRetryableError,
    DeliveryCtx,
    EvaluationSummary,
)
from pareeksha.integrations.crypto import SecretBox
from pareeksha.integrations.delivery import (
    DeliveryService,
    InMemoryDeliveryStore,
    IntegrationRecord,
)
from pareeksha.integrations.hubspot import (
    HubSpotConfig,
    HubSpotConnector,
    HubSpotSecrets,
    render_note,
)
from pareeksha.integrations.registry import ConnectorRegistry
from pareeksha.integrations.webhook import WebhookConfig

TOKEN = "pat-na1-synthetic-token"
SEC = HubSpotSecrets(private_app_token=TOKEN)


def make(handler: Callable[[httpx.Request], httpx.Response]) -> HubSpotConnector:
    return HubSpotConnector(transport=httpx.MockTransport(handler))


def evaluation(
    metadata: dict[str, str] | None = None, passed: bool | None = False
) -> tuple[AnyEnvelope, EvaluationSummary]:
    call_id = uuid.uuid4()
    env = make_envelope(
        EvaluationCompleted(
            call_id=call_id, evaluation_id=uuid.uuid4(), overall_score=40.0, passed=bool(passed)
        ),
        producer="t",
        correlation_id=str(call_id),
    )
    summary = EvaluationSummary(
        call_id=call_id,
        agent_name="EMI Reminder Bot",
        source="import",
        language="kn-IN",
        duration_ms=84_000,
        overall_score=40.0,
        passed=passed,
        critical_failure=True,
        failure_types=["asr_misrecognition", "wrong_fact"],
        summary="Misheard 4,000 as 40,000.",
        link="/calls/abc",
        metadata={"phone": "+919999900000"} if metadata is None else metadata,
    )
    return env, summary


def ctx_for(summary: EvaluationSummary | None) -> DeliveryCtx:
    return DeliveryCtx(
        integration_id=uuid.uuid4(), delivery_id=uuid.uuid4(), attempt=1, summary=summary
    )


def setup(**cfg: object) -> tuple[DeliveryService, IntegrationRecord]:
    box = SecretBox(Fernet.generate_key())
    record = IntegrationRecord(
        id=uuid.uuid4(),
        connector="hubspot",
        config={"public_base_url": "https://app.example.com", **cfg},
        secrets_encrypted=box.encrypt({"private_app_token": TOKEN}),
    )
    return DeliveryService(InMemoryDeliveryStore(), box), record


class Portal:
    """Tiny HubSpot double: contact search plus note creation, notes counted."""

    def __init__(self, contact_ids: list[str] | None = None) -> None:
        self.contacts = ["501"] if contact_ids is None else contact_ids
        self.searches: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.url.path == "/crm/v3/objects/contacts/search":
            self.searches.append(json.loads(request.content))
            return httpx.Response(200, json={"results": [{"id": c} for c in self.contacts]})
        if request.url.path == "/crm/v3/objects/notes":
            self.notes.append(json.loads(request.content))
            return httpx.Response(201, json={"id": f"note-{len(self.notes)}"})
        return httpx.Response(404)


async def test_phone_match_creates_one_associated_note() -> None:
    portal = Portal()
    service, record = setup()
    env, summary = evaluation()
    row = await service.deliver(make(portal), record, env, summary=summary)
    assert row.status == "succeeded" and row.external_id == "note-1" and row.http_status == 201
    groups = portal.searches[0]["filterGroups"]
    assert {g["filters"][0]["propertyName"] for g in groups} == {"phone", "mobilephone"}
    (note,) = portal.notes
    assoc = note["associations"][0]
    assert assoc["to"] == {"id": "501"}
    assert assoc["types"] == [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]
    props = note["properties"]
    assert props["hs_timestamp"].endswith("Z")
    assert "FAIL (40/100) CRITICAL" in props["hs_note_body"]
    assert "Agent: EMI Reminder Bot - kn-IN - 1m 24s" in props["hs_note_body"]
    assert "Issues: asr_misrecognition, wrong_fact" in props["hs_note_body"]
    assert "https://app.example.com/calls/abc" in props["hs_note_body"]
    assert str(env.event_id) in props["hs_note_body"]


async def test_redelivery_and_replay_create_exactly_one_note() -> None:
    portal = Portal()
    service, record = setup()
    env, summary = evaluation()
    connector = make(portal)
    first = await service.deliver(connector, record, env, summary=summary)
    for _ in range(3):
        again = await service.deliver(connector, record, env, summary=summary)
        assert again.external_id == first.external_id == "note-1"
    assert len(portal.notes) == 1 and len(portal.searches) == 1


async def test_retry_after_failure_still_one_note() -> None:
    portal = Portal()
    fail = {"on": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/crm/v3/objects/notes" and fail["on"]:
            fail["on"] = False
            return httpx.Response(503)
        return portal(request)

    service, record = setup()
    env, summary = evaluation()
    connector = make(handler)
    with pytest.raises(ConnectorRetryableError):
        await service.deliver(connector, record, env, summary=summary)
    row = await service.deliver(connector, record, env, summary=summary)
    assert row.status == "succeeded" and row.attempts == 2 and len(portal.notes) == 1


async def test_contact_id_in_metadata_skips_search() -> None:
    portal = Portal()
    service, record = setup()
    env, summary = evaluation({"crm_contact_id": "77"})
    row = await service.deliver(make(portal), record, env, summary=summary)
    assert row.status == "succeeded" and not portal.searches
    assert portal.notes[0]["associations"][0]["to"] == {"id": "77"}


async def test_email_match() -> None:
    portal = Portal()
    service, record = setup(match_by="email")
    env, summary = evaluation({"email": "A@Example.com"})
    row = await service.deliver(make(portal), record, env, summary=summary)
    assert row.status == "succeeded"
    assert portal.searches[0]["filterGroups"] == [
        {"filters": [{"propertyName": "email", "operator": "EQ", "value": "a@example.com"}]}
    ]


@pytest.mark.parametrize(
    ("cfg", "meta"),
    [
        ({}, {}),  # no phone
        ({"match_by": "email"}, {"phone": "+911"}),  # no email
        ({"match_by": "contact_id"}, {"phone": "+911"}),  # no id
    ],
)
async def test_missing_identifier_is_skipped(cfg: dict[str, str], meta: dict[str, str]) -> None:
    portal = Portal()
    service, record = setup(**cfg)
    env, summary = evaluation(meta)
    row = await service.deliver(make(portal), record, env, summary=summary)
    assert row.status == "skipped" and "no matching contact" in (row.response_excerpt or "")
    assert not portal.notes


async def test_no_contact_found_is_skipped_and_replay_stays_skipped() -> None:
    portal = Portal(contact_ids=[])
    service, record = setup()
    env, summary = evaluation()
    row = await service.deliver(make(portal), record, env, summary=summary)
    assert row.status == "skipped" and not portal.notes
    await service.deliver(make(portal), record, env, summary=summary)
    assert len(portal.searches) == 1


async def test_only_failed_and_missing_summary_skipped() -> None:
    portal = Portal()
    service, record = setup(only_failed=True)
    env, summary = evaluation(passed=True)
    row = await service.deliver(make(portal), record, env, summary=summary)
    assert row.status == "skipped" and not portal.searches
    env2, _ = evaluation()
    row2 = await service.deliver(make(portal), record, env2, summary=None)
    assert row2.status == "skipped"


@pytest.mark.parametrize(("status", "word"), [(401, "invalid or revoked"), (403, "scopes")])
async def test_bad_token_gives_clear_permanent_error(status: int, word: str) -> None:
    service, record = setup()
    env, summary = evaluation()
    row = await service.deliver(
        make(lambda r: httpx.Response(status)), record, env, summary=summary
    )
    assert row.status == "failed" and word in (row.response_excerpt or "")


async def test_429_carries_retry_after_and_400_is_permanent() -> None:
    env, summary = evaluation()
    ctx = ctx_for(summary)
    limited = make(lambda r: httpx.Response(429, headers={"retry-after": "7"}))
    with pytest.raises(ConnectorRetryableError) as info:
        await limited.handle(env, HubSpotConfig(), SEC, ctx)
    assert info.value.retry_after_s == 7.0
    bad = make(lambda r: httpx.Response(400, text="nope"))
    with pytest.raises(ConnectorPermanentError, match="400"):
        await bad.handle(env, HubSpotConfig(), SEC, ctx)


async def test_transport_errors_are_retryable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("search"):
            raise httpx.ConnectTimeout("t")
        raise httpx.ConnectError("c")

    env, summary = evaluation()
    with pytest.raises(ConnectorRetryableError, match="timeout"):
        await make(boom).handle(env, HubSpotConfig(), SEC, ctx_for(summary))
    _, with_id = evaluation({"crm_contact_id": "1"})
    with pytest.raises(ConnectorRetryableError, match="transport"):
        await make(boom).handle(env, HubSpotConfig(), SEC, ctx_for(with_id))


async def test_note_without_id_in_response_is_permanent() -> None:
    connector = make(lambda r: httpx.Response(201, json={}))
    env, summary = evaluation({"crm_contact_id": "1"})
    with pytest.raises(ConnectorPermanentError, match="no id"):
        await connector.handle(env, HubSpotConfig(), SEC, ctx_for(summary))


async def test_test_method() -> None:
    ok = await make(lambda r: httpx.Response(200, json={"results": []})).test(HubSpotConfig(), SEC)
    assert ok.ok
    bad = await make(lambda r: httpx.Response(401)).test(HubSpotConfig(), SEC)
    assert not bad.ok and "401" in bad.detail


async def test_wrong_config_types_rejected() -> None:
    env, summary = evaluation()
    with pytest.raises(ConnectorPermanentError, match="wrong type"):
        await make(lambda r: httpx.Response(200)).handle(
            env, WebhookConfig(url="https://x.example.com"), SEC, ctx_for(summary)
        )


def test_render_note_variants() -> None:
    _, summary = evaluation()
    ctx = ctx_for(summary)
    bare = summary.model_copy(
        update={
            "passed": None,
            "overall_score": None,
            "critical_failure": False,
            "failure_types": [],
            "agent_name": None,
            "language": None,
            "duration_ms": None,
            "link": "https://x.example.com/c",
        }
    )
    text = render_note(HubSpotConfig(), bare, ctx, "e1")
    assert "UNSCORED (n/a/100)" in text and "Issues: none" in text and "0m 0s" in text
    assert "https://x.example.com/c" in text and "unknown agent" in text
    custom = render_note(HubSpotConfig(note_template="{{ verdict }}"), summary, ctx, "e1")
    assert custom.startswith("FAIL\n")
    with pytest.raises(ConnectorPermanentError, match="note_template"):
        render_note(HubSpotConfig(note_template="{{ oops "), summary, ctx, "e1")


def test_registered_as_builtin() -> None:
    registry = ConnectorRegistry.from_entry_points()
    assert registry.get("hubspot") is HubSpotConnector
