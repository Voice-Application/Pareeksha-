"""``python -m pareeksha.workers.dlq_recorder``: copy ``dlq.v1`` into ``dead_letters`` (TRD 10.5).

The table feeds the DLQ page and replay. The write is an upsert on ``(event_id, consumer_group)``:
a re-delivered DLQ message changes nothing, and a message that fails again after being replayed
re-opens its row. Unparseable messages are stored too (``envelope = {"raw": "<text>"}``, event id
derived from the bytes) so nothing that reached the DLQ is lost. There is no DLQ for the DLQ: a
database fault makes the recorder back off and re-read the message.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.structs import OffsetAndMetadata
from psycopg.types.json import Jsonb

from pareeksha.events.runtime import (
    HEADER_CONSUMER_GROUP,
    Database,
    configure_logging,
    decode_headers,
    install_stop_signals,
)
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import HEADER_ERROR, HEADER_TARGET_TOPIC, ConsumerGroups, Topics

log = logging.getLogger(__name__)

_UPSERT = """
INSERT INTO dead_letters (event_id, original_topic, key, consumer_group, envelope, error, attempts)
VALUES (%(event_id)s, %(original_topic)s, %(key)s, %(consumer_group)s, %(envelope)s, %(error)s,
        %(attempts)s)
ON CONFLICT (event_id, consumer_group) DO UPDATE
SET status = 'open', error = EXCLUDED.error, attempts = EXCLUDED.attempts,
    envelope = EXCLUDED.envelope, failed_at = now(), replayed_at = NULL
WHERE dead_letters.status = 'replayed'
"""


@dataclass(frozen=True, slots=True)
class DeadLetter:
    event_id: uuid.UUID
    original_topic: str
    key: str
    consumer_group: str
    envelope: dict[str, Any]
    error: str
    attempts: int


def to_dead_letter(
    value: bytes | None, key: bytes | None, headers: dict[str, str], fallback_topic: str
) -> DeadLetter:
    """Build the ``dead_letters`` row for one ``dlq.v1`` message (never raises)."""
    raw = value or b""
    envelope: dict[str, Any]
    try:
        parsed = json.loads(raw)
        envelope = parsed if isinstance(parsed, dict) else {"raw": parsed}
    except ValueError:
        envelope = {"raw": raw.decode("utf-8", errors="replace")}
    try:
        event_id = uuid.UUID(str(envelope["event_id"]))
    except (KeyError, ValueError):
        event_id = uuid.uuid5(uuid.NAMESPACE_OID, hashlib.sha256(raw).hexdigest())
    attempt = envelope.get("attempt")
    return DeadLetter(
        event_id=event_id,
        original_topic=headers.get(HEADER_TARGET_TOPIC, fallback_topic),
        key=(key or b"").decode("utf-8", errors="replace"),
        consumer_group=headers.get(HEADER_CONSUMER_GROUP, "unknown"),
        envelope=envelope,
        error=headers.get(HEADER_ERROR, "unknown error"),
        attempts=attempt if isinstance(attempt, int) and attempt >= 1 else 1,
    )


async def record(conn: psycopg.AsyncConnection[Any], dl: DeadLetter) -> None:
    await conn.execute(
        _UPSERT,
        {
            "event_id": dl.event_id,
            "original_topic": dl.original_topic,
            "key": dl.key,
            "consumer_group": dl.consumer_group,
            "envelope": Jsonb(dl.envelope),
            "error": dl.error,
            "attempts": dl.attempts,
        },
    )


class DlqRecorder:
    def __init__(
        self,
        settings: EventSettings,
        *,
        group: str = ConsumerGroups.DLQ_RECORDER,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._settings = settings
        self._auto_offset_reset = auto_offset_reset
        self.group = str(group)
        self._db = Database(settings)
        self._consumer: Any = None
        self._ready = asyncio.Event()
        self.stop_event = asyncio.Event()
        self.recorded = 0

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            Topics.DLQ.value,
            bootstrap_servers=self._settings.bootstrap_servers,
            group_id=self.group,
            enable_auto_commit=False,
            auto_offset_reset=self._auto_offset_reset,
        )
        await self._consumer.start()
        self._ready.set()

    async def wait_ready(self, timeout: float = 30.0) -> None:
        async def _wait() -> None:
            await self._ready.wait()
            while not self._consumer.assignment():
                await asyncio.sleep(0.1)
            for tp in self._consumer.assignment():
                await self._consumer.position(tp)

        await asyncio.wait_for(_wait(), timeout)

    async def process(self, rec: Any) -> None:
        dl = to_dead_letter(rec.value, rec.key, decode_headers(rec.headers), rec.topic)
        await record(await self._db.connection(), dl)
        await self._consumer.commit(
            {TopicPartition(rec.topic, rec.partition): OffsetAndMetadata(rec.offset + 1, "")}
        )
        self.recorded += 1
        log.info(
            "dead letter recorded",
            extra={
                "group": dl.consumer_group,
                "event_id": str(dl.event_id),
                "topic": dl.original_topic,
            },
        )

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
                            log.exception("dlq-recorder failed; will re-read the message")
                            self._consumer.seek(tp, rec.offset)
                            with contextlib.suppress(TimeoutError):
                                await asyncio.wait_for(self.stop_event.wait(), backoff)
        finally:
            await self._consumer.stop()
            await self._db.close()


async def main() -> None:
    configure_logging()
    recorder = DlqRecorder(EventSettings.from_env())
    install_stop_signals(recorder.stop_event)
    await recorder.run()


if __name__ == "__main__":
    asyncio.run(main())
