"""Shared pieces of the Kafka suite (QA-02): real broker, Alembic-migrated Postgres, real consumers.

Unlike the INFRA-02 tests (which build the three plumbing tables from ``docs/schema.sql``), this
suite runs on the database Alembic produces and writes real domain rows (``evaluations``), so it
also proves the framework works with the production schema.

Environment (the defaults match ``docker compose up -d kafka postgres kafka-init``):
  INFRA_TEST_KAFKA_BOOTSTRAP  default localhost:9094  (the broker's published port)
  TEST_DATABASE_URL           server used for the throw-away migrated database (tests/conftest.py)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from aiokafka import AIOKafkaConsumer

from pareeksha.events.consumer import ConsumerRunner, ConsumerSpec, Ctx, Outgoing, RetryPolicy
from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import AnyEnvelope, CallCompleted, EvaluationCompleted, make_envelope
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
from pareeksha.workers.dlq_recorder import DlqRecorder
from pareeksha.workers.retrier import Retrier
from tests.integration.support import prime_group, read_topic, wait_for

__all__ = ["BOOTSTRAP", "prime_group", "read_topic", "wait_for"]

BOOTSTRAP = os.environ.get("INFRA_TEST_KAFKA_BOOTSTRAP", "localhost:9094")
FAST = RetryPolicy(delay_seconds={2: 0.5, 3: 1.0}, throttle_delay_seconds=0.5)
RUBRIC = "rubric-2026-10-v1"


def settings_for(database_url: str) -> EventSettings:
    """Worker settings for the throw-away database (SQLAlchemy URL -> libpq URL)."""
    return EventSettings(
        bootstrap_servers=BOOTSTRAP,
        database_url=database_url.replace("postgresql+psycopg://", "postgresql://", 1),
    )


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------------------------
# Database rows the handlers need
# ---------------------------------------------------------------------------------------------


def seed_calls(settings: EventSettings, n: int = 1) -> list[uuid.UUID]:
    """``n`` uploaded calls (and the project / rubric they hang off); returns the call ids."""
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO rubric_versions (version, dimensions, prompt_hash) VALUES (%s, '{}', 'h') "
            "ON CONFLICT (version) DO NOTHING",
            (RUBRIC,),
        )
        row = conn.execute(
            "INSERT INTO projects (name) VALUES (%s) RETURNING id", (unique("qa"),)
        ).fetchone()
        assert row is not None
        ids: list[uuid.UUID] = []
        for _ in range(n):
            call = conn.execute(
                "INSERT INTO calls (project_id, source, status, end_reason) "
                "VALUES (%s, 'upload', 'completed', 'upload') RETURNING id",
                (row[0],),
            ).fetchone()
            assert call is not None
            ids.append(call[0])
        return ids


def scalar(settings: EventSettings, sql: str, *params: Any) -> Any:
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def evaluation_count(settings: EventSettings, call_id: uuid.UUID) -> int:
    return int(scalar(settings, "SELECT count(*) FROM evaluations WHERE call_id = %s", call_id))


def call_completed(call_id: uuid.UUID, *, event_id: uuid.UUID | None = None) -> AnyEnvelope:
    return make_envelope(
        CallCompleted(call_id=call_id, source="upload", end_reason="upload"),
        producer="qa-02",
        correlation_id=str(call_id),
        event_id=event_id,
    )


# ---------------------------------------------------------------------------------------------
# Handlers that write the real tables (used in-process and by the crash worker)
# ---------------------------------------------------------------------------------------------


def evaluation_id_for(call_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(call_id, "evaluation")


def _evaluation_event(call_id: uuid.UUID) -> Outgoing:
    return Outgoing(
        EvaluationCompleted(
            call_id=call_id,
            evaluation_id=evaluation_id_for(call_id),
            overall_score=88.0,
            passed=True,
        )
    )


async def evaluate(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    """``call.completed`` -> one ``evaluations`` row (plain INSERT: a second run would violate
    ``evaluations_call_id_rubric_version_id_key``, so only the framework's dedupe prevents it)."""
    call_id = env.payload.call_id
    await ctx.tx.execute(
        "INSERT INTO evaluations (id, call_id, rubric_version_id, judge_model, prompt_hash, "
        "dimensions, overall_score, passed) "
        "SELECT %s, %s, id, 'qa-double', 'h', '{}'::jsonb, 88, true FROM rubric_versions "
        "WHERE version = %s",
        (evaluation_id_for(call_id), call_id, RUBRIC),
    )
    return [_evaluation_event(call_id)]


async def evaluate_again(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    """``reproduce`` for a duplicate: rebuild the output from what is stored, write nothing."""
    call_id = env.payload.call_id
    row = await (
        await ctx.tx.execute("SELECT id FROM evaluations WHERE call_id = %s", (call_id,))
    ).fetchone()
    assert row is not None, "duplicate of an event whose evaluation is missing"
    return [_evaluation_event(call_id)]


NOTES_DDL = (
    "CREATE TABLE IF NOT EXISTS qa_crm_notes (call_id uuid PRIMARY KEY, "
    "evaluation_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now())"
)


async def write_note(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    """``evaluation.completed`` -> one CRM-note row per call (primary key = one note)."""
    await ctx.tx.execute(
        "INSERT INTO qa_crm_notes (call_id, evaluation_id) VALUES (%s, %s)",
        (env.payload.call_id, env.payload.evaluation_id),
    )
    return []


def prepare_notes_table(settings: EventSettings) -> None:
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute(NOTES_DDL)


# ---------------------------------------------------------------------------------------------
# Running consumers in-process
# ---------------------------------------------------------------------------------------------


@dataclass
class Running:
    runner: ConsumerRunner
    producer: EventProducer
    retrier_group: str | None = None
    recorder_group: str | None = None

    async def send(self, env: AnyEnvelope) -> None:
        await self.producer.publish(env)


@asynccontextmanager
async def consumer(
    settings: EventSettings,
    spec: ConsumerSpec,
    *,
    policy: RetryPolicy | None = None,
    with_retry_path: bool = False,
) -> Any:
    """Start ``spec`` (and optionally the retrier and DLQ recorder) on fresh primed groups."""
    await prime_group(spec.group, list(spec.topics))
    producer = EventProducer(settings.bootstrap_servers, client_id=unique("qa-producer"))
    await producer.start()
    runner = ConsumerRunner(spec, settings, policy=policy)
    parts: list[Any] = [runner]
    running = Running(runner, producer)
    if with_retry_path:
        running.retrier_group, running.recorder_group = unique("qa-retrier"), unique("qa-dlq")
        await prime_group(running.retrier_group, [Topics.RETRY_30S, Topics.RETRY_5M])
        await prime_group(running.recorder_group, [Topics.DLQ])
        parts += [
            Retrier(settings, group=running.retrier_group),
            DlqRecorder(settings, group=running.recorder_group),
        ]
    tasks = [asyncio.create_task(p.run()) for p in parts]
    try:
        for p in parts:
            await p.wait_ready()
        yield running
    finally:
        for p in parts:
            p.stop_event.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await producer.stop()
        for r in results:
            if isinstance(r, BaseException):
                raise r


def spec_for(
    group: str,
    topic: Topics,
    handler: Callable[[Any, Ctx], Awaitable[Sequence[Outgoing]]],
    reproduce: Callable[[Any, Ctx], Awaitable[Sequence[Outgoing]]] | None = None,
) -> ConsumerSpec:
    return ConsumerSpec(group=group, topics=(topic,), handler=handler, reproduce=reproduce)


async def publish_once(settings: EventSettings, env: AnyEnvelope) -> None:
    """Produce one event with its own short-lived producer."""
    producer = EventProducer(settings.bootstrap_servers, client_id=unique("qa-once"))
    await producer.start()
    try:
        await producer.publish(env)
    finally:
        await producer.stop()


async def lag(group: str, topics: Sequence[Topics]) -> dict[str, int]:
    """End offset minus committed offset for every partition of ``topics``."""
    probe: Any = AIOKafkaConsumer(*[t.value for t in topics], bootstrap_servers=BOOTSTRAP)
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


async def lag_is_zero(group: str, topics: Sequence[Topics]) -> bool:
    return all(v == 0 for v in (await lag(group, topics)).values())


# ---------------------------------------------------------------------------------------------
# The broker as a Docker container (real outage)
# ---------------------------------------------------------------------------------------------


class Broker:
    """Stops and starts the container publishing the broker port (compose or `docker run`)."""

    def __init__(self) -> None:
        port = BOOTSTRAP.rsplit(":", 1)[1]
        found = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"publish={port}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert len(found) == 1, f"expected one container publishing port {port}, found {found}"
        self.container = found[0]

    def stop(self) -> None:
        subprocess.run(
            ["docker", "stop", "-t", "5", self.container], check=True, capture_output=True
        )

    def start(self, timeout: float = 90.0) -> None:
        subprocess.run(["docker", "start", self.container], check=True, capture_output=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            probe = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container,
                    "/opt/kafka/bin/kafka-broker-api-versions.sh",
                    "--bootstrap-server",
                    "localhost:9092",
                ],
                capture_output=True,
            )
            if probe.returncode == 0:
                return
            time.sleep(1)
        raise AssertionError("broker did not come back")

    def is_running(self) -> bool:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", self.container],
            capture_output=True,
            text=True,
        ).stdout.strip()
        return out == "true"
