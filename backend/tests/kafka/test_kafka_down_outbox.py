"""T-NFR-4b: the API keeps accepting work while Kafka is down; the outbox drains in per-key order.

The broker is a real container that this test stops and starts (``docker stop`` / ``docker
start``), not a mocked producer. The relay is the real ``OutboxRelay``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient

from pareeksha.events.outbox import backlog, enqueue
from pareeksha.events.schemas import AuditRequested, make_envelope
from pareeksha.events.topics import Topics
from pareeksha.workers.outbox_relay import OutboxRelay
from tests.conftest import Tenant
from tests.kafka.kit import BOOTSTRAP, Broker, read_topic, settings_for, wait_for

KEYS = 3
PER_KEY = 4


def audit(call_id: uuid.UUID, seq: int) -> Any:
    payload = AuditRequested(
        call_id=call_id, source="upload", language="kn-IN", recording_ref=f"seq-{seq}"
    )
    return make_envelope(payload, producer="qa-02", correlation_id=str(call_id))


@pytest.fixture
def broker() -> Any:
    b = Broker()
    assert b.is_running()
    yield b
    if not b.is_running():  # never leave the shared broker down if the test failed midway
        b.start()


async def test_api_accepts_while_kafka_is_down_and_the_outbox_drains_in_per_key_order(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    broker: Broker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", BOOTSTRAP)
    settings = settings_for(database_url)
    keys = [uuid.uuid4() for _ in range(KEYS)]

    relay = OutboxRelay(settings, poll_interval=0.2, request_timeout_ms=3000)
    relay_task = asyncio.create_task(relay.run())
    conn = await psycopg.AsyncConnection.connect(settings.database_url, autocommit=True)
    await conn.execute(
        "DELETE FROM outbox_events"
    )  # rows left by earlier tests sharing this database
    try:
        healthy = await api.get("/api/v1/health")
        assert healthy.status_code == 200 and healthy.json() == {"db": "ok", "kafka": "ok"}

        broker.stop()
        down = await api.get("/api/v1/health")
        assert down.status_code == 503
        assert down.json()["db"] == "ok" and down.json()["kafka"].startswith("down")

        # requests that need only the database keep succeeding
        created = await api.post(
            "/api/v1/agents",
            json={"name": "Written while Kafka is down", "endpoint_url": "ws://x:1/ws"},
            headers=tenant.admin,
        )
        assert created.status_code == 201

        # events accepted during the outage, interleaved across keys, each in its own transaction
        for seq in range(PER_KEY):
            for key in keys:
                async with conn.transaction():
                    await enqueue(conn, audit(key, seq))
        assert await backlog(conn) == KEYS * PER_KEY

        async def relay_tried() -> bool:
            row = await (
                await conn.execute(
                    "SELECT count(*) FROM outbox_events WHERE published_at IS NULL AND attempts > 0"
                )
            ).fetchone()
            return row is not None and row[0] > 0

        await wait_for(relay_tried, timeout=90, what="the relay to try, fail and record last_error")
        failed = await (
            await conn.execute(
                "SELECT last_error FROM outbox_events WHERE published_at IS NULL AND attempts > 0"
            )
        ).fetchone()
        assert failed is not None and failed[0]
        assert await backlog(conn) == KEYS * PER_KEY  # nothing was lost or half-published

        broker.start()

        async def drained() -> bool:
            return await backlog(conn) == 0

        await wait_for(drained, timeout=120, interval=1.0, what="the outbox to drain")
        recovered = await api.get("/api/v1/health")
        assert recovered.status_code == 200
    finally:
        relay.stop_event.set()
        await asyncio.wait_for(
            relay_task, 90
        )  # producer.stop() flushes; slow right after a broker restart
        await conn.close()

    duplicates = 0
    for key in keys:
        messages = await read_topic(Topics.AUDIT_REQUESTED, key=str(key))
        seen: dict[str, str] = {}
        for m in messages:  # topic order = per-key partition order
            body = json.loads(m.value)
            if body["event_id"] in seen:
                duplicates += 1  # a send that timed out during the outage can land later
                continue
            seen[body["event_id"]] = body["payload"]["recording_ref"]
        assert list(seen.values()) == [f"seq-{n}" for n in range(PER_KEY)], (
            f"key {key}: events left the outbox out of order"
        )
    print(f"duplicates after the outage (at-least-once, deduped by event_id): {duplicates}")
