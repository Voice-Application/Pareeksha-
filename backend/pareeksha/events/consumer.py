"""Consumer framework (TRD section 10.5).

    @consumer(group="evaluator", topic=Topics.CALL_COMPLETED)
    async def handle(env: Envelope[CallCompleted], ctx: Ctx) -> list[Outgoing]:
        ...  # do work inside ctx.tx (a DB transaction); return the events to produce

For each message the runner (one message at a time per instance):

1. parses the envelope (malformed / unknown type -> DLQ);
2. opens a DB transaction and inserts ``(group, event_id)`` into ``processed_events``; a conflict
   means the event was already handled, so the handler is skipped and, if a ``reproduce``
   callback exists, its outputs are produced again (their event ids are deterministic);
3. runs the handler inside that transaction, commits, **then** produces the returned events and
   **then** commits the Kafka offset (``enable_auto_commit=False``);
4. on an exception classifies it: retryable -> copy with ``attempt+1`` to ``retry.30s`` /
   ``retry.5m``; permanent or attempts exhausted -> ``dlq.v1``; ``Throttled`` -> ``retry.30s``
   with the same attempt. The offset is committed after the copy is produced, so the partition
   never blocks.

Infrastructure faults (Kafka produce fails, Postgres connection lost around the framework's own
SQL) do not consume an attempt: the offset is not committed, the runner seeks back to the message
and retries after a backoff. SIGTERM stops polling after the current message.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import psycopg
import pydantic
from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.structs import OffsetAndMetadata

from pareeksha.events.producer import EventProducer
from pareeksha.events.runtime import (
    HEADER_CONSUMER_GROUP,
    Database,
    configure_logging,
    decode_headers,
    install_stop_signals,
    utc_iso,
)
from pareeksha.events.schemas import (
    AnyEnvelope,
    EventPayload,
    make_envelope,
    parse_envelope,
)
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import (
    HEADER_ERROR,
    HEADER_NOT_BEFORE,
    HEADER_REASON,
    HEADER_TARGET_TOPIC,
    MAX_ATTEMPTS,
    REASON_THROTTLED,
    RETRY_DELAY_SECONDS,
    Topics,
    retry_topic_for_attempt,
)

log = logging.getLogger(__name__)

MAX_ERROR_CHARS = 500


# ---------------------------------------------------------------------------------------------
# Handler-facing types
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outgoing:
    """An event a handler wants produced after its transaction commits.

    The envelope ``event_id`` is ``uuid5(input_event_id, output_type)`` (AGENTS.md 6.1). A handler
    that emits several events of one type from one input (the planner's fan-out of
    ``call.requested``) must give each a ``discriminator`` (e.g. the run_item_id) so the ids stay
    distinct yet deterministic.
    """

    payload: EventPayload
    discriminator: str | None = None
    correlation_id: str | None = None
    #: Explicit event id, for outputs whose identity is not "one per input event" (the finalizer's
    #: ``run.completed`` is one per run: ``uuid5(run_id, ...)``). Must still be deterministic.
    event_id: uuid.UUID | None = None


@dataclass(slots=True)
class Ctx:
    """Passed to handlers. ``tx`` is an open transaction; commit/rollback is the framework's."""

    tx: psycopg.AsyncConnection[Any]
    group: str
    topic: str
    partition: int
    offset: int
    attempt: int
    #: True while ``reproduce`` runs for an event this group already processed.
    duplicate: bool = False


Handler = Callable[[Any, Ctx], Awaitable[Sequence[Outgoing]]]


class RetryableError(Exception):
    """Raise from a handler for a transient failure (retry.30s -> retry.5m -> DLQ)."""


class PermanentError(Exception):
    """Raise from a handler for a failure retrying cannot fix (straight to the DLQ)."""


class Throttled(Exception):
    """Raise from a handler when the run is at its concurrency cap (TRD section 10.6).

    The message goes to ``retry.30s`` with ``x-reason: throttled`` and its ``attempt`` is NOT
    incremented, so waiting for a slot never exhausts the retry budget.
    """


class Disposition(StrEnum):
    RETRY = "retry"
    PERMANENT = "permanent"


def _http_status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def classify(exc: BaseException) -> Disposition:
    """Retryable vs permanent (TRD 10.5 step 4).

    Retryable: ``RetryableError``, timeouts, connection / OS errors, database connectivity
    errors, HTTP 5xx / 408 / 429, and any unrecognised exception (attempts are bounded, so a
    bug costs three tries before it lands in the DLQ). Permanent: ``PermanentError``, schema /
    validation errors (``ValueError``, ``TypeError``, ``KeyError``, pydantic), HTTP 4xx, SQL
    data / programming errors.
    """
    if isinstance(exc, RetryableError):
        return Disposition.RETRY
    if isinstance(exc, PermanentError):
        return Disposition.PERMANENT
    status = _http_status(exc)
    if status is not None:
        return Disposition.RETRY if status >= 500 or status in (408, 429) else Disposition.PERMANENT
    if isinstance(exc, (TimeoutError, OSError, psycopg.OperationalError, psycopg.InterfaceError)):
        return Disposition.RETRY
    if isinstance(
        exc,
        (
            pydantic.ValidationError,
            ValueError,
            TypeError,
            KeyError,
            psycopg.DataError,
            psycopg.ProgrammingError,
        ),
    ):
        return Disposition.PERMANENT
    return Disposition.RETRY


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Delays before a retry-topic message is redelivered (defaults: the frozen contract)."""

    delay_seconds: Mapping[int, float] = field(default_factory=lambda: dict(RETRY_DELAY_SECONDS))
    #: Delay for throttled messages (they use ``retry.30s``).
    throttle_delay_seconds: float = float(RETRY_DELAY_SECONDS[2])

    def delay(self, next_attempt: int) -> float:
        return float(self.delay_seconds[next_attempt])


# ---------------------------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConsumerSpec:
    group: str
    topics: tuple[Topics, ...]
    handler: Handler
    #: Read-only function returning the outputs of an already-processed event (see module doc).
    reproduce: Handler | None = None
    max_poll_interval_ms: int = 300_000
    auto_offset_reset: str = "earliest"


#: Every consumer declared with ``@consumer``, by group id.
REGISTRY: dict[str, ConsumerSpec] = {}


def consumer(
    *,
    group: str,
    topic: Topics | Sequence[Topics],
    reproduce: Handler | None = None,
    max_poll_interval_ms: int = 300_000,
    auto_offset_reset: str = "earliest",
) -> Callable[[Handler], Handler]:
    """Register ``handler`` as the consumer of ``group`` on ``topic``."""
    topics = (topic,) if isinstance(topic, Topics) else tuple(topic)

    def register(handler: Handler) -> Handler:
        REGISTRY[str(group)] = ConsumerSpec(
            group=str(group),
            topics=topics,
            handler=handler,
            reproduce=reproduce,
            max_poll_interval_ms=max_poll_interval_ms,
            auto_offset_reset=auto_offset_reset,
        )
        return handler

    return register


# ---------------------------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------------------------


class _InfrastructureError(Exception):
    """The framework's own database work failed (not the handler's)."""


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]


class ConsumerRunner:
    """Runs one consumer group member. Parallelism = instances (<= partitions)."""

    def __init__(
        self,
        spec: ConsumerSpec,
        settings: EventSettings,
        *,
        producer: EventProducer | None = None,
        policy: RetryPolicy | None = None,
    ) -> None:
        self.spec = spec
        self.group = spec.group
        self._settings = settings
        self._policy = policy or RetryPolicy()
        self._own_producer = producer is None
        self._producer = producer or EventProducer(
            settings.bootstrap_servers, client_id=f"{spec.group}-producer"
        )
        self._db = Database(settings)
        self._consumer: Any = None
        self._ready = asyncio.Event()
        self.stop_event = asyncio.Event()
        self._producer_name = f"{spec.group}@{socket.gethostname()}"

    # -- lifecycle ----------------------------------------------------------------------------

    async def start(self) -> None:
        if self._own_producer:
            await self._producer.start()
        self._consumer = AIOKafkaConsumer(
            *[t.value for t in self.spec.topics],
            bootstrap_servers=self._settings.bootstrap_servers,
            group_id=self.group,
            client_id=f"{self.group}-{os.getpid()}",
            enable_auto_commit=False,
            auto_offset_reset=self.spec.auto_offset_reset,
            max_poll_interval_ms=self.spec.max_poll_interval_ms,
        )
        await self._consumer.start()
        self._ready.set()

    async def wait_ready(self, timeout: float = 30.0) -> None:
        """Wait until partitions are assigned and start offsets are resolved."""

        async def _wait() -> None:
            await self._ready.wait()
            while not self._consumer.assignment():
                await asyncio.sleep(0.1)
            for tp in self._consumer.assignment():
                await self._consumer.position(tp)

        await asyncio.wait_for(_wait(), timeout)

    def stop(self) -> None:
        """Ask the run loop to finish the current message and exit."""
        self.stop_event.set()

    async def _shutdown(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()  # leaves the group
        if self._own_producer:
            await self._producer.stop()
        await self._db.close()

    async def run(self) -> None:
        await self.start()
        backoff = 0.0
        try:
            while not self.stop_event.is_set():
                batch = await self._consumer.getmany(timeout_ms=500, max_records=1)
                for tp, records in batch.items():
                    for rec in records:
                        try:
                            await self.process(rec)
                            backoff = 0.0
                        except Exception:
                            backoff = min(max(backoff * 2, 0.5), 10.0)
                            log.exception(
                                "infrastructure failure; message will be redelivered",
                                extra={
                                    "group": self.group,
                                    "topic": rec.topic,
                                    "offset": rec.offset,
                                },
                            )
                            self._consumer.seek(tp, rec.offset)
                            with contextlib.suppress(TimeoutError):
                                await asyncio.wait_for(self.stop_event.wait(), backoff)
        finally:
            await self._shutdown()

    # -- one message --------------------------------------------------------------------------

    async def process(self, rec: Any) -> None:
        """Handle one record end to end; returns after the offset is committed.

        Raises only for infrastructure faults, which ``run`` turns into a seek-back and retry.
        """
        headers = decode_headers(rec.headers)
        only_group = headers.get(HEADER_CONSUMER_GROUP)
        if only_group is not None and only_group != self.group:
            # a retry/DLQ-replay copy meant for another group on the same topic
            await self._commit(rec)
            return

        try:
            env = self._parse(rec)
        except Exception as exc:
            log.warning(
                "unparseable message -> DLQ", extra={"group": self.group, "topic": rec.topic}
            )
            await self._send_failure(rec, Topics.DLQ, rec.value or b"", exc)
            await self._commit(rec)
            return

        extra = {
            "group": self.group,
            "event_id": str(env.event_id),
            "correlation_id": env.correlation_id,
            "topic": rec.topic,
            "attempt": env.attempt,
        }
        try:
            outputs = await self._transact(env, rec)
        except Throttled as exc:
            log.info("throttled -> retry.30s (attempt unchanged)", extra=extra)
            await self._send_failure(
                rec,
                Topics.RETRY_30S,
                rec.value,
                exc,
                delay=self._policy.throttle_delay_seconds,
                reason=REASON_THROTTLED,
            )
        except _InfrastructureError as exc:
            raise exc.__cause__ or exc from None
        except Exception as exc:
            await self._route_failure(rec, env, exc, extra)
        else:
            for out in outputs:
                await self._producer.publish(self._build_output(env, out))
            log.info("processed", extra=extra)
        await self._commit(rec)

    def _parse(self, rec: Any) -> AnyEnvelope:
        if rec.value is None:
            raise PermanentError("message has no value")
        env = parse_envelope(rec.value)
        if env.topic.value != rec.topic:
            raise PermanentError(f"event type {env.type.value} does not belong on {rec.topic}")
        return env

    async def _transact(self, env: AnyEnvelope, rec: Any) -> Sequence[Outgoing]:
        conn = await self._db.connection()
        in_handler = False
        try:
            async with conn.transaction():
                cur = await conn.execute(
                    "INSERT INTO processed_events (consumer_group, event_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING RETURNING 1",
                    (self.group, env.event_id),
                )
                duplicate = await cur.fetchone() is None
                ctx = Ctx(
                    tx=conn,
                    group=self.group,
                    topic=rec.topic,
                    partition=rec.partition,
                    offset=rec.offset,
                    attempt=env.attempt,
                    duplicate=duplicate,
                )
                in_handler = True
                if duplicate:
                    log.log(
                        logging.INFO if self.spec.reproduce else logging.WARNING,
                        "duplicate delivery; %s",
                        "re-producing outputs"
                        if self.spec.reproduce
                        else "no reproduce callback, outputs (if any) are not re-produced",
                        extra={"group": self.group, "event_id": str(env.event_id)},
                    )
                    outputs = await self.spec.reproduce(env, ctx) if self.spec.reproduce else []
                else:
                    outputs = await self.spec.handler(env, ctx)
                in_handler = False
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            if in_handler:
                raise
            raise _InfrastructureError from exc
        return outputs

    def _build_output(self, inp: AnyEnvelope, out: Outgoing) -> AnyEnvelope:
        etype = out.payload.event_type
        event_id = out.event_id or uuid.uuid5(
            inp.event_id, f"{etype.value}:{out.discriminator}" if out.discriminator else etype.value
        )
        return make_envelope(
            out.payload,
            producer=self._producer_name,
            correlation_id=out.correlation_id or inp.correlation_id,
            causation_id=inp.event_id,
            event_id=event_id,
        )

    async def _route_failure(
        self, rec: Any, env: AnyEnvelope, exc: Exception, extra: Mapping[str, Any]
    ) -> None:
        disposition = classify(exc)
        if disposition is Disposition.RETRY and env.attempt < MAX_ATTEMPTS:
            nxt = env.attempt + 1
            log.warning(
                "handler failed (%s) -> retry attempt %d", _error_text(exc), nxt, extra=extra
            )
            copy = env.model_copy(update={"attempt": nxt})
            await self._send_failure(
                rec,
                retry_topic_for_attempt(nxt),
                copy.to_json_bytes(),
                exc,
                delay=self._policy.delay(nxt),
            )
        else:
            log.error(
                "handler failed (%s) -> DLQ after %d attempt(s)",
                _error_text(exc),
                env.attempt,
                extra=extra,
            )
            await self._send_failure(rec, Topics.DLQ, rec.value, exc)

    async def _send_failure(
        self,
        rec: Any,
        topic: Topics,
        value: bytes,
        exc: BaseException,
        *,
        delay: float | None = None,
        reason: str | None = None,
    ) -> None:
        headers = {
            HEADER_TARGET_TOPIC: rec.topic,
            HEADER_ERROR: _error_text(exc),
            HEADER_CONSUMER_GROUP: self.group,
        }
        if delay is not None:
            headers[HEADER_NOT_BEFORE] = utc_iso(datetime.now(UTC) + timedelta(seconds=delay))
        if reason is not None:
            headers[HEADER_REASON] = reason
        await self._producer.send(topic.value, value, key=rec.key, headers=headers)

    async def _commit(self, rec: Any) -> None:
        tp = TopicPartition(rec.topic, rec.partition)
        await self._consumer.commit({tp: OffsetAndMetadata(rec.offset + 1, "")})


async def run_worker(group: str) -> None:
    """Entry point for ``python -m pareeksha.workers.<name>``: run the registered consumer."""
    configure_logging()
    runner = ConsumerRunner(REGISTRY[group], EventSettings.from_env())
    install_stop_signals(runner.stop_event)
    await runner.run()
