"""Transactional outbox and relay against real Postgres and Kafka."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from aiokafka.errors import KafkaConnectionError

from pareeksha.events.outbox import backlog, enqueue, prune_published, relay_once
from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import AnyEnvelope, parse_envelope
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
from pareeksha.workers.outbox_relay import OutboxRelay
from tests.integration.support import (
    SETTINGS,
    TEST_DB_URL,
    audit_envelope,
    read_topic,
    wait_for,
)


@pytest.fixture(autouse=True)
def _clean_outbox() -> None:
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE outbox_events")


def _event_id(value: bytes) -> str | None:
    try:
        return str(json.loads(value)["event_id"])
    except (ValueError, KeyError, TypeError):  # other tests leave garbage messages on this topic
        return None


async def _connect() -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(TEST_DB_URL, autocommit=True)


async def _started_producer() -> EventProducer:
    producer = EventProducer(SETTINGS.bootstrap_servers, client_id="outbox-test")
    await producer.start()
    return producer


class FlakyProducer(EventProducer):
    """Real producer whose broker 'goes away' after ``ok_sends`` successful publishes."""

    def __init__(self, ok_sends: int) -> None:
        super().__init__(SETTINGS.bootstrap_servers, client_id="flaky")
        self.ok_sends = ok_sends

    async def send(self, topic: str, value: bytes, **kwargs: Any) -> None:
        if self.ok_sends <= 0:
            raise KafkaConnectionError("broker unavailable")
        self.ok_sends -= 1
        await super().send(topic, value, **kwargs)


async def test_rolled_back_transaction_leaves_no_event_and_committed_one_is_published() -> None:
    lost, kept = audit_envelope(), audit_envelope()
    conn = await _connect()
    try:
        try:
            async with conn.transaction():
                await enqueue(conn, lost)
                raise RuntimeError("domain write failed")
        except RuntimeError:
            pass
        async with conn.transaction():
            await enqueue(conn, kept)
        assert await backlog(conn) == 1

        producer = await _started_producer()
        try:
            result = await relay_once(conn, producer)
            again = await relay_once(conn, producer)
        finally:
            await producer.stop()
        assert (result.published, result.failed, again.published) == (1, 0, 0)
        row = await (
            await conn.execute(
                "SELECT published_at, attempts, last_error FROM outbox_events WHERE id = %s",
                (kept.event_id,),
            )
        ).fetchone()
    finally:
        await conn.close()

    assert row is not None and row[0] is not None and row[1] == 1 and row[2] is None
    assert await read_topic(Topics.AUDIT_REQUESTED, key=str(lost.payload.call_id)) == []
    (msg,) = await read_topic(Topics.AUDIT_REQUESTED, key=str(kept.payload.call_id))
    assert parse_envelope(msg.value).event_id == kept.event_id


async def test_concurrent_relays_publish_each_row_exactly_once() -> None:
    envs: list[AnyEnvelope] = [audit_envelope() for _ in range(30)]
    ids = {str(e.event_id) for e in envs}
    setup = await _connect()
    async with setup.transaction():
        for e in envs:
            await enqueue(setup, e)
    await setup.close()

    async def one_relay() -> int:
        conn = await _connect()
        producer = await _started_producer()
        try:
            total = 0
            while True:
                r = await relay_once(conn, producer, batch_size=7)
                total += r.published
                if r.published == 0:
                    return total
        finally:
            await producer.stop()
            await conn.close()

    totals = await asyncio.gather(*(one_relay() for _ in range(3)))
    assert sum(totals) == 30

    published = [
        eid for m in await read_topic(Topics.AUDIT_REQUESTED) if (eid := _event_id(m.value)) in ids
    ]
    assert sorted(published) == sorted(ids), "every event exactly once, none duplicated"


async def test_broker_outage_keeps_rows_and_drains_after_recovery() -> None:
    envs = [audit_envelope() for _ in range(3)]
    conn = await _connect()
    try:
        async with conn.transaction():
            for e in envs:
                await enqueue(conn, e)

        flaky = FlakyProducer(ok_sends=1)
        await flaky.start()
        try:
            down = await relay_once(conn, flaky)
        finally:
            await flaky.stop()
        assert (down.published, down.failed) == (1, 1)
        assert "KafkaConnectionError" in (down.last_error or "")
        assert await backlog(conn) == 2
        rows = await (
            await conn.execute(
                "SELECT attempts, last_error FROM outbox_events "
                "WHERE published_at IS NULL ORDER BY attempts DESC"
            )
        ).fetchall()
        assert rows[0][0] == 1 and "broker unavailable" in rows[0][1] and rows[1][0] == 0

        producer = await _started_producer()  # broker is back
        try:
            up = await relay_once(conn, producer)
        finally:
            await producer.stop()
        assert (up.published, up.failed) == (2, 0)
        assert await backlog(conn) == 0
    finally:
        await conn.close()

    for e in envs:
        assert len(await read_topic(Topics.AUDIT_REQUESTED, key=str(e.payload.call_id))) == 1


async def test_relay_worker_drains_the_outbox_and_stops_cleanly() -> None:
    env = audit_envelope()
    conn = await _connect()
    async with conn.transaction():
        await enqueue(conn, env)

    relay = OutboxRelay(SETTINGS, poll_interval=0.1)
    task = asyncio.create_task(relay.run())

    async def drained() -> bool:
        return await backlog(conn) == 0

    try:
        await wait_for(drained, what="outbox drained by the relay worker")
        # new rows keep flowing while it runs
        second = audit_envelope()
        async with conn.transaction():
            await enqueue(conn, second)
        await wait_for(drained, what="second row drained")
    finally:
        relay.stop_event.set()
        await asyncio.wait_for(task, 30)
        await conn.close()
    assert relay.published_total == 2
    assert len(await read_topic(Topics.AUDIT_REQUESTED, key=str(env.payload.call_id))) == 1


async def test_relay_worker_survives_unreachable_kafka() -> None:
    env = audit_envelope()
    conn = await _connect()
    async with conn.transaction():
        await enqueue(conn, env)

    dead = EventSettings(bootstrap_servers="localhost:1", database_url=TEST_DB_URL)
    relay = OutboxRelay(dead, poll_interval=0.1, request_timeout_ms=1000)
    task = asyncio.create_task(relay.run())
    await asyncio.sleep(3)
    assert not task.done(), "the relay must keep retrying, not crash"
    assert await backlog(conn) == 1
    relay.stop_event.set()
    await asyncio.wait_for(task, 30)
    await conn.close()


async def test_prune_removes_only_old_published_rows() -> None:
    old, fresh, pending = audit_envelope(), audit_envelope(), audit_envelope()
    conn = await _connect()
    try:
        async with conn.transaction():
            for e in (old, fresh, pending):
                await enqueue(conn, e)
        await conn.execute(
            "UPDATE outbox_events SET published_at = now() - interval '4 days' WHERE id = %s",
            (old.event_id,),
        )
        await conn.execute(
            "UPDATE outbox_events SET published_at = now() WHERE id = %s", (fresh.event_id,)
        )
        assert await prune_published(conn, timedelta(days=3)) == 1
        left = {r[0] for r in await (await conn.execute("SELECT id FROM outbox_events")).fetchall()}
    finally:
        await conn.close()
    assert left == {fresh.event_id, pending.event_id}


async def test_send_is_bounded_by_the_delivery_timeout() -> None:
    producer = EventProducer(SETTINGS.bootstrap_servers, delivery_timeout_s=1.0)
    await producer.start()
    try:
        # auto topic creation is off, so the producer waits for metadata that never arrives
        with pytest.raises(TimeoutError):
            await producer.send("pareeksha.no-such-topic.v1", b"{}", key=b"k")
    finally:
        await producer.stop()
