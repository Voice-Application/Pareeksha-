"""Server-Sent Events for ``GET /runs/{id}/events`` (FR-RG-3, NFR-16).

Source of truth for the first message is Postgres (``snapshot``: the run and its matrix rows);
everything after it comes from the ``pareeksha.progress.v1`` topic, read by a private group-less
consumer per connection (no consumer group is created, nothing is committed).

Reconnect: every message carries an ``id:`` that encodes the last offset read on every partition
(``0:41,1:7,...``). The browser's ``EventSource`` sends it back as ``Last-Event-ID``; the server
sends a fresh ``snapshot`` first (spec) and then replays what that connection missed from the
stored offsets, so no event is lost. Events are at-least-once and may be older than the snapshot
that precedes them (all events of a run share a partition and arrive in order, so the last one
wins and the client ends in the right state). Without a valid ``Last-Event-ID`` the stream starts
at the end of every partition.

The stream ends after ``run.completed`` (also when the run was already finished at connect time).
A comment line (``: heartbeat``) is sent after ``heartbeat_s`` of silence (default 15 s).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from pareeksha.api.errors import ApiError
from pareeksha.db.models import Calls
from pareeksha.db.session import SessionFactory
from pareeksha.events.schemas import ProgressEvent, parse_envelope
from pareeksha.events.topics import Topics
from pareeksha.runs import service
from pareeksha.schemas.runs import (
    SseCallEvaluated,
    SseItemStatus,
    SseRunCompleted,
    SseRunCompletedSummary,
    SseSnapshot,
)

log = logging.getLogger(__name__)

HEARTBEAT_S = 15.0
_POLL_MS = 500
_TOPIC = Topics.PROGRESS.value


def format_event(name: str, data: BaseModel, event_id: str) -> str:
    return f"id: {event_id}\nevent: {name}\ndata: {data.model_dump_json()}\n\n"


def encode_cursor(offsets: dict[int, int]) -> str:
    return ",".join(f"{p}:{o}" for p, o in sorted(offsets.items()))


def decode_cursor(value: str | None) -> dict[int, int] | None:
    """``{partition: last offset read}`` from a ``Last-Event-ID``; ``None`` if it is not ours."""
    if not value:
        return None
    try:
        pairs = [part.split(":") for part in value.split(",")]
        out = {int(p): int(o) for p, o in pairs}
    except ValueError:
        return None
    return out if all(p >= 0 and o >= -1 for p, o in out.items()) else None


class ProgressStream:
    """One SSE connection: owns a Kafka consumer, yields ready-to-send SSE text."""

    def __init__(
        self,
        bootstrap_servers: str,
        session_factory: SessionFactory,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        *,
        last_event_id: str | None = None,
        heartbeat_s: float = HEARTBEAT_S,
    ) -> None:
        self._bootstrap = bootstrap_servers
        self._factory = session_factory
        self._project_id = project_id
        self._run_id = run_id
        self._resume = decode_cursor(last_event_id)
        self._heartbeat_s = heartbeat_s
        self._consumer: Any = None
        self._cursor: dict[int, int] = {}

    async def open(self) -> None:
        """Connect and position the consumer. 502 when Kafka cannot be reached."""
        consumer = AIOKafkaConsumer(
            _TOPIC,
            bootstrap_servers=self._bootstrap,
            group_id=None,
            enable_auto_commit=False,
            auto_offset_reset="latest",
            client_id="pareeksha-sse",
        )
        try:
            await asyncio.wait_for(consumer.start(), timeout=10)
            partitions = await self._wait_assignment(consumer)
            ends = await consumer.end_offsets(partitions)
            resume = self._resume or {}
            for tp in partitions:
                start = resume.get(tp.partition)
                if start is None or start + 1 > ends[tp]:
                    consumer.seek(tp, ends[tp])
                    self._cursor[tp.partition] = ends[tp] - 1
                else:
                    consumer.seek(tp, start + 1)
                    self._cursor[tp.partition] = start
        except Exception as exc:
            with contextlib.suppress(Exception):
                await consumer.stop()
            raise ApiError(
                502, "upstream_error", "The progress stream is unavailable (Kafka unreachable)"
            ) from exc
        self._consumer = consumer

    @staticmethod
    async def _wait_assignment(consumer: Any) -> list[TopicPartition]:
        async def _wait() -> list[TopicPartition]:
            while not consumer.assignment():
                await asyncio.sleep(0.05)
            return sorted(consumer.assignment(), key=lambda tp: tp.partition)

        return await asyncio.wait_for(_wait(), timeout=10)

    async def close(self) -> None:
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            with contextlib.suppress(Exception):
                await consumer.stop()

    def _id(self) -> str:
        return encode_cursor(self._cursor)

    async def events(self) -> AsyncGenerator[str]:
        try:
            async with self._factory() as session:
                run = await service.get_run(session, self._project_id, self._run_id)
                items = await service.all_items(session, self._project_id, self._run_id)
            yield format_event("snapshot", SseSnapshot(run=run, items=items), self._id())
            if run.status in service.FINISHED_RUN_STATUSES:
                summary = SseRunCompletedSummary(
                    pass_rate=run.summary.pass_rate, critical_failures=run.summary.critical_failures
                )
                yield format_event(
                    "run.completed", SseRunCompleted(run_id=run.id, summary=summary), self._id()
                )
                return
            async for chunk in self._follow():
                yield chunk
        finally:
            await self.close()

    async def _follow(self) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        last_sent = loop.time()
        while self._consumer is not None:
            batches = await self._consumer.getmany(timeout_ms=_POLL_MS)
            for tp, records in batches.items():
                for record in records:
                    self._cursor[tp.partition] = record.offset
                    sse = await self._translate(record.value)
                    if sse is None:
                        continue
                    name, data = sse
                    last_sent = loop.time()
                    yield format_event(name, data, self._id())
                    if name == "run.completed":
                        return
            if loop.time() - last_sent >= self._heartbeat_s:
                last_sent = loop.time()
                yield ": heartbeat\n\n"

    async def _translate(self, raw: bytes) -> tuple[str, BaseModel] | None:
        """The SSE event for one progress message of this run, or ``None`` to skip it."""
        try:
            payload = parse_envelope(raw).payload
        except Exception:
            log.warning("unreadable message on the progress topic skipped", exc_info=True)
            return None
        if not isinstance(payload, ProgressEvent) or payload.run_id != self._run_id:
            return None
        try:
            if payload.kind == "item.status":
                assert payload.run_item_id is not None and payload.status is not None
                return "item.status", SseItemStatus.model_validate(
                    {
                        "run_item_id": payload.run_item_id,
                        "status": payload.status,
                        "scenario": payload.scenario,
                        "persona": payload.persona,
                    }
                )
            if payload.kind == "call.evaluated":
                assert payload.call_id is not None
                assert payload.overall_score is not None and payload.passed is not None
                run_item_id = payload.run_item_id or await self._run_item_of(payload.call_id)
                if run_item_id is None:
                    return None
                return "call.evaluated", SseCallEvaluated(
                    run_item_id=run_item_id,
                    call_id=payload.call_id,
                    overall_score=payload.overall_score,
                    passed=payload.passed,
                    critical_failure=bool(payload.critical_failure),
                )
            return "run.completed", SseRunCompleted(
                run_id=self._run_id,
                summary=SseRunCompletedSummary(
                    pass_rate=payload.pass_rate, critical_failures=payload.critical_failures
                ),
            )
        except ValidationError:
            log.warning("progress event does not fit its SSE schema, skipped", exc_info=True)
            return None

    async def _run_item_of(self, call_id: uuid.UUID) -> uuid.UUID | None:
        async with self._factory() as session:
            return await session.scalar(select(Calls.run_item_id).where(Calls.id == call_id))
