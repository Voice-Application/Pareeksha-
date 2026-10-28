"""GET /dlq, POST /dlq/{id}/replay, POST /dlq/{id}/discard (API-04, FR-IN-10).

Real app, real Postgres. The replay test also drives the real outbox relay and reads the message
back from Kafka.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import psycopg
from httpx import AsyncClient
from sqlalchemy import select

from pareeksha.db import models
from pareeksha.events.outbox import relay_once
from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import parse_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.events.topics import Topics
from tests.conftest import Tenant
from tests.integration.api04_support import Factory
from tests.integration.runs_support import API
from tests.integration.support import BOOTSTRAP, audit_envelope, read_topic, wait_for


async def _dead_letter(
    factory: Factory,
    *,
    envelope: dict[str, Any] | None = None,
    status: str = "open",
    group: str = "auditor",
    age: timedelta = timedelta(0),
    attempts: int = 3,
) -> models.DeadLetters:
    env = audit_envelope(attempt=attempts)
    data = envelope if envelope is not None else json.loads(env.model_dump_json())
    async with factory() as session:
        row = models.DeadLetters(
            event_id=uuid.UUID(str(data.get("event_id", uuid.uuid4()))),
            original_topic=Topics.AUDIT_REQUESTED.value,
            key=str(env.partition_key()),
            consumer_group=group,
            envelope=data,
            error="PermanentError: bad audio",
            attempts=attempts,
            status=status,
            failed_at=datetime.now(UTC) - age,
        )
        session.add(row)
        await session.commit()
        return row


async def test_list_filters_by_status_newest_first_and_pages(
    private_api: tuple[AsyncClient, Tenant, Factory],
) -> None:
    api, tenant, session_factory = private_api
    await _dead_letter(session_factory, status="replayed")
    await _dead_letter(session_factory, status="discarded")
    old = await _dead_letter(session_factory, age=timedelta(hours=2))
    mid = await _dead_letter(session_factory, age=timedelta(hours=1), group="evaluator")
    new = await _dead_letter(session_factory)

    page = (await api.get(f"{API}/dlq?limit=2", headers=tenant.read)).json()
    ours = [new.id, mid.id]
    assert [i["id"] for i in page["items"]] == [str(i) for i in ours]
    assert page["next_cursor"]
    rest = (
        await api.get(
            f"{API}/dlq", params={"limit": 200, "cursor": page["next_cursor"]}, headers=tenant.read
        )
    ).json()
    assert [i["id"] for i in rest["items"]] == [str(old.id)] and rest["next_cursor"] is None

    row = page["items"][0]
    assert set(row) == {
        "id", "event_id", "original_topic", "consumer_group", "error", "attempts", "status",
        "failed_at", "envelope",
    }  # fmt: skip
    assert row["status"] == "open" and row["attempts"] == 3
    assert row["original_topic"] == Topics.AUDIT_REQUESTED.value
    assert row["envelope"]["type"] == "audit.requested"
    replayed = (await api.get(f"{API}/dlq?status=replayed&limit=200", headers=tenant.read)).json()
    assert replayed["items"] and all(i["status"] == "replayed" for i in replayed["items"])
    assert (await api.get(f"{API}/dlq?status=bogus", headers=tenant.read)).status_code == 400
    assert (await api.get(f"{API}/dlq")).status_code == 401


async def test_discard_marks_the_row_and_is_not_repeatable(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    row = await _dead_letter(session_factory)
    response = await api.post(f"{API}/dlq/{row.id}/discard", headers=tenant.admin)
    assert response.status_code == 200 and response.json()["status"] == "discarded"
    async with session_factory() as session:
        assert (await session.get(models.DeadLetters, row.id)).status == "discarded"  # type: ignore[union-attr]
        published = await session.scalars(
            select(models.OutboxEvents).where(models.OutboxEvents.key == row.key)
        )
        assert list(published) == []  # discarding publishes nothing
    again = await api.post(f"{API}/dlq/{row.id}/discard", headers=tenant.admin)
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict"
    replay = await api.post(f"{API}/dlq/{row.id}/replay", headers=tenant.admin)
    assert replay.status_code == 409


async def test_replay_republishes_the_envelope_with_attempt_1_through_the_outbox(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, database_url: str
) -> None:
    row = await _dead_letter(session_factory, attempts=3)
    response = await api.post(f"{API}/dlq/{row.id}/replay", headers=tenant.admin)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "replayed" and response.json()["id"] == str(row.id)

    async with session_factory() as session:
        stored = await session.get(models.DeadLetters, row.id)
        assert stored is not None and stored.status == "replayed" and stored.replayed_at
        outbox = list(
            await session.scalars(
                select(models.OutboxEvents).where(
                    models.OutboxEvents.topic == Topics.AUDIT_REQUESTED.value,
                    models.OutboxEvents.key == row.key,
                )
            )
        )
    assert len(outbox) == 1 and outbox[0].published_at is None
    queued = parse_envelope(cast("dict[str, Any]", outbox[0].envelope))
    assert queued.attempt == 1 and queued.event_id == row.event_id  # same event, first attempt
    assert outbox[0].id != row.event_id

    # the real relay publishes it to the original topic
    producer = EventProducer(BOOTSTRAP)
    await producer.start()
    try:
        async with await psycopg.AsyncConnection.connect(
            libpq_url(database_url), autocommit=True
        ) as conn:
            result = await relay_once(conn, producer)
    finally:
        await producer.stop()
    assert result.published >= 1 and result.failed == 0

    async def arrived() -> bool:
        seen = await read_topic(Topics.AUDIT_REQUESTED, key=row.key)
        got = [json.loads(s.value) for s in seen]
        return any(g["event_id"] == str(row.event_id) and g["attempt"] == 1 for g in got)

    await wait_for(arrived, what="the replayed event on audit.requested")

    again = await api.post(f"{API}/dlq/{row.id}/replay", headers=tenant.admin)
    assert again.status_code == 409


async def test_replay_refuses_a_message_that_is_not_an_envelope(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    row = await _dead_letter(session_factory, envelope={"raw": "not json {"}, attempts=1)
    response = await api.post(f"{API}/dlq/{row.id}/replay", headers=tenant.admin)
    assert response.status_code == 409
    assert "not a valid event envelope" in response.json()["error"]["message"]
    async with session_factory() as session:
        assert (await session.get(models.DeadLetters, row.id)).status == "open"  # type: ignore[union-attr]
        outbox = await session.scalars(
            select(models.OutboxEvents).where(models.OutboxEvents.key == row.key)
        )
        assert list(outbox) == []


async def test_replay_and_discard_need_admin_and_a_known_row(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    row = await _dead_letter(session_factory)
    for action in ("replay", "discard"):
        denied = await api.post(f"{API}/dlq/{row.id}/{action}", headers=tenant.read)
        assert denied.status_code == 403
        missing = await api.post(f"{API}/dlq/{uuid.uuid4()}/{action}", headers=tenant.admin)
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    async with session_factory() as session:
        assert (await session.get(models.DeadLetters, row.id)).status == "open"  # type: ignore[union-attr]
