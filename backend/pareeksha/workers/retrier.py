"""``python -m pareeksha.workers.retrier``: delay topics -> original topics (TRD section 10.5).

Consumes ``retry.30s`` and ``retry.5m``. A message carries ``x-not-before``; until then its
partition is paused (the consumer keeps polling so the group membership stays alive, even for the
5-minute topic) and the message is re-read when due. Messages inside one delay topic are already
in due-time order. Due messages are produced to ``x-target-topic`` (same key, same value, with
``x-consumer-group`` kept so only the group that failed reprocesses it) and then the offset is
committed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.structs import OffsetAndMetadata

from pareeksha.events.producer import EventProducer
from pareeksha.events.runtime import (
    HEADER_CONSUMER_GROUP,
    configure_logging,
    decode_headers,
    install_stop_signals,
    parse_utc,
)
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import (
    HEADER_ERROR,
    HEADER_NOT_BEFORE,
    HEADER_TARGET_TOPIC,
    ConsumerGroups,
    Topics,
)

log = logging.getLogger(__name__)

#: Headers copied onto the redelivered message (the rest are retrier bookkeeping).
_FORWARDED_HEADERS = (HEADER_CONSUMER_GROUP, HEADER_ERROR)


class Retrier:
    def __init__(
        self,
        settings: EventSettings,
        *,
        group: str = ConsumerGroups.RETRIER,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._settings = settings
        self._auto_offset_reset = auto_offset_reset
        self.group = str(group)
        self._producer = EventProducer(
            settings.bootstrap_servers, client_id=f"{self.group}-producer"
        )
        self._consumer: Any = None
        self._ready = asyncio.Event()
        self.stop_event = asyncio.Event()
        self._paused: dict[TopicPartition, datetime] = {}
        self.forwarded = 0

    async def start(self) -> None:
        await self._producer.start()
        self._consumer = AIOKafkaConsumer(
            Topics.RETRY_30S.value,
            Topics.RETRY_5M.value,
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

    def _resume_due(self) -> None:
        now = datetime.now(UTC)
        assigned = self._consumer.assignment()
        for tp, due in list(self._paused.items()):
            if tp not in assigned:
                del self._paused[tp]  # rebalanced away
            elif due <= now:
                self._consumer.resume(tp)
                del self._paused[tp]

    async def process(self, rec: Any) -> None:
        """Forward one due message, or pause its partition until it is due."""
        headers = decode_headers(rec.headers)
        tp = TopicPartition(rec.topic, rec.partition)
        target = headers.get(HEADER_TARGET_TOPIC)
        if not target:
            # cannot be routed: park it in the DLQ so it is visible rather than lost
            await self._producer.send(
                Topics.DLQ.value,
                rec.value or b"",
                key=rec.key,
                headers={
                    **{k: v for k, v in headers.items() if k != HEADER_NOT_BEFORE},
                    HEADER_ERROR: "retry message without x-target-topic",
                },
            )
        else:
            not_before = parse_utc(headers.get(HEADER_NOT_BEFORE, ""))
            if not_before is not None and not_before > datetime.now(UTC):
                self._consumer.seek(tp, rec.offset)  # re-read it when due
                self._consumer.pause(tp)
                self._paused[tp] = not_before
                return
            await self._producer.send(
                target,
                rec.value or b"",
                key=rec.key,
                headers={k: v for k, v in headers.items() if k in _FORWARDED_HEADERS},
            )
            self.forwarded += 1
            log.info(
                "redelivered to %s",
                target,
                extra={"group": self.group, "topic": rec.topic, "offset": rec.offset},
            )
        await self._consumer.commit({tp: OffsetAndMetadata(rec.offset + 1, "")})

    async def run(self) -> None:
        await self.start()
        backoff = 0.0
        try:
            while not self.stop_event.is_set():
                self._resume_due()
                batch = await self._consumer.getmany(timeout_ms=500, max_records=1)
                for tp, records in batch.items():
                    for rec in records:
                        try:
                            await self.process(rec)
                            backoff = 0.0
                        except Exception:
                            backoff = min(max(backoff * 2, 0.5), 10.0)
                            log.exception("retrier failed; will re-read the message")
                            self._consumer.seek(tp, rec.offset)
                            with contextlib.suppress(TimeoutError):
                                await asyncio.wait_for(self.stop_event.wait(), backoff)
        finally:
            await self._consumer.stop()
            await self._producer.stop()


async def main() -> None:
    configure_logging()
    retrier = Retrier(EventSettings.from_env())
    install_stop_signals(retrier.stop_event)
    await retrier.run()


if __name__ == "__main__":
    asyncio.run(main())
