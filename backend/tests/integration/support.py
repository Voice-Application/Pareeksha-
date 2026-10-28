"""Helpers for the Kafka + Postgres integration tests (real broker, real database).

Environment (defaults match ``docker compose up -d kafka postgres kafka-init``):
  INFRA_TEST_KAFKA_BOOTSTRAP  default localhost:9094
  INFRA_TEST_DATABASE_URL  default postgresql://pareeksha:pareeksha@localhost:5432/pareeksha_events_test
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from aiokafka import AIOKafkaConsumer
from aiokafka.structs import OffsetAndMetadata

from pareeksha.events.runtime import decode_headers
from pareeksha.events.schemas import AuditRequested, CallCompleted, make_envelope
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics

BOOTSTRAP = os.environ.get("INFRA_TEST_KAFKA_BOOTSTRAP", "localhost:9094")
TEST_DB_URL = os.environ.get(
    "INFRA_TEST_DATABASE_URL",
    "postgresql://pareeksha:pareeksha@localhost:5432/pareeksha_events_test",
)
SCHEMA_SQL = Path(__file__).resolve().parents[3] / "docs" / "schema.sql"

SETTINGS = EventSettings(bootstrap_servers=BOOTSTRAP, database_url=TEST_DB_URL)

#: Kafka plumbing tables, taken verbatim from docs/schema.sql (API-01 turns them into Alembic).
_PLUMBING = (
    "outbox_events",
    "outbox_unpublished",
    "processed_events",
    "dead_letters",
    "dead_letters_open",
)

SIDE_EFFECTS_DDL = """
CREATE TABLE IF NOT EXISTS it_side_effects (
    id        bigserial PRIMARY KEY,
    grp       text NOT NULL,
    event_id  uuid NOT NULL,
    note      text NOT NULL DEFAULT ''
)
"""


def plumbing_ddl() -> list[str]:
    text = SCHEMA_SQL.read_text(encoding="utf-8")
    out: list[str] = []
    for m in re.finditer(r"CREATE (TABLE|INDEX) (\w+)\b.*?;", text, flags=re.DOTALL):
        if m.group(2) in _PLUMBING:
            out.append(
                m.group(0).replace(
                    f"CREATE {m.group(1)} ", f"CREATE {m.group(1)} IF NOT EXISTS ", 1
                )
            )
    assert len(out) == len(_PLUMBING), f"expected {len(_PLUMBING)} statements, found {len(out)}"
    return out


def prepare_database() -> None:
    """Create the test database if needed and apply the plumbing tables (idempotent)."""
    base, _, name = TEST_DB_URL.rpartition("/")
    with psycopg.connect(f"{base}/postgres", autocommit=True) as admin:
        if (
            admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
            is None
        ):
            admin.execute(
                psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name))
            )
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        for stmt in plumbing_ddl():
            conn.execute(stmt)
        conn.execute(SIDE_EFFECTS_DDL)


def unique_group(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def audit_envelope(call_id: uuid.UUID | None = None, *, attempt: int = 1) -> Any:
    """A valid ``audit.requested`` envelope (key: call_id)."""
    cid = call_id or uuid.uuid4()
    payload = AuditRequested(
        call_id=cid, source="upload", language="kn-IN", recording_ref="blob://x"
    )
    return make_envelope(payload, producer="test@host", correlation_id=str(cid), attempt=attempt)


def completed_payload(call_id: uuid.UUID) -> CallCompleted:
    return CallCompleted(call_id=call_id, source="upload")


@dataclass(frozen=True, slots=True)
class Seen:
    topic: str
    partition: int
    offset: int
    key: str
    value: bytes
    headers: dict[str, str]


async def prime_group(group: str, topics: list[Topics]) -> None:
    """Commit the group's offsets at the current end so it starts exactly at 'now'.

    A fresh group would otherwise replay the topic's whole history (or, with ``latest``, race
    the test's first produce); with committed offsets, a restarted member resumes correctly.
    """
    consumer: Any = AIOKafkaConsumer(
        *[t.value for t in topics],
        bootstrap_servers=BOOTSTRAP,
        group_id=group,
        enable_auto_commit=False,
        auto_offset_reset="latest",
    )
    await consumer.start()
    try:
        while not consumer.assignment():
            await consumer.getmany(timeout_ms=200)
        offsets = {
            tp: OffsetAndMetadata(await consumer.position(tp), "") for tp in consumer.assignment()
        }
        await consumer.commit(offsets)
    finally:
        await consumer.stop()


async def read_topic(topic: Topics | str, *, key: str | None = None) -> list[Seen]:
    """Everything currently in ``topic`` (optionally for one key), read without a group."""
    name = topic.value if isinstance(topic, Topics) else topic
    consumer: Any = AIOKafkaConsumer(
        name,
        bootstrap_servers=BOOTSTRAP,
        group_id=None,  # no group: all partitions are assigned directly
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        tps = sorted(consumer.assignment(), key=lambda tp: tp.partition)
        ends = await consumer.end_offsets(tps)
        out: list[Seen] = []
        while any([await consumer.position(tp) < ends[tp] for tp in tps]):
            batch = await consumer.getmany(timeout_ms=500)
            for recs in batch.values():
                for r in recs:
                    k = (r.key or b"").decode()
                    if key is None or k == key:
                        out.append(
                            Seen(
                                r.topic,
                                r.partition,
                                r.offset,
                                k,
                                r.value,
                                decode_headers(r.headers),
                            )
                        )
        return out
    finally:
        await consumer.stop()


async def wait_for(
    probe: Callable[[], Awaitable[Any]],
    *,
    timeout: float = 30.0,
    interval: float = 0.25,
    what: str = "",
) -> Any:
    """Poll ``probe`` until it returns something truthy; fail with ``what`` on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        result = await probe()
        if result:
            return result
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for: {what}")
        await asyncio.sleep(interval)


async def group_lag(group: str, topics: list[Topics]) -> dict[str, int]:
    """Lag per ``topic/partition`` of ``group`` (end offset minus committed offset)."""
    names = [t.value for t in topics]
    probe: Any = AIOKafkaConsumer(*names, bootstrap_servers=BOOTSTRAP, group_id=None)
    await probe.start()
    try:
        tps = sorted(probe.assignment(), key=lambda tp: (tp.topic, tp.partition))
        ends = await probe.end_offsets(tps)
    finally:
        await probe.stop()
    reader: Any = AIOKafkaConsumer(
        bootstrap_servers=BOOTSTRAP, group_id=group, enable_auto_commit=False
    )
    await reader.start()
    try:
        return {
            f"{tp.topic}/{tp.partition}": ends[tp] - ((await reader.committed(tp)) or 0)
            for tp in tps
        }
    finally:
        await reader.stop()


def db() -> psycopg.Connection[Any]:
    return psycopg.connect(TEST_DB_URL, autocommit=True)


def side_effects(group: str, event_id: uuid.UUID) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT count(*) FROM it_side_effects WHERE grp = %s AND event_id = %s",
            (group, event_id),
        ).fetchone()
    assert row is not None
    return int(row[0])
