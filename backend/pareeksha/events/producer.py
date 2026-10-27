"""Idempotent Kafka producer (``acks=all``) used by the outbox relay and the consumer framework."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from aiokafka import AIOKafkaProducer

from pareeksha.events.runtime import encode_headers
from pareeksha.events.schemas import AnyEnvelope

log = logging.getLogger(__name__)

STOP_TIMEOUT_S = 15.0


class EventProducer:
    """Thin wrapper over ``AIOKafkaProducer`` with the settings TRD section 10.4 requires."""

    def __init__(
        self,
        bootstrap_servers: str,
        *,
        client_id: str = "pareeksha",
        request_timeout_ms: int = 10_000,
        delivery_timeout_s: float = 20.0,
    ) -> None:
        self._producer: Any = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            acks="all",
            enable_idempotence=True,
            request_timeout_ms=request_timeout_ms,
        )
        self._delivery_timeout_s = delivery_timeout_s
        self._started = False

    async def start(self) -> None:
        if not self._started:
            await self._producer.start()
            self._started = True

    async def stop(self) -> None:
        if self._started:
            self._started = False
            try:
                # stop() flushes; sends that already timed out may still retry against a broker
                # that went away, and a flush that never ends must not block a worker's shutdown.
                await asyncio.wait_for(self._producer.stop(), STOP_TIMEOUT_S)
            except TimeoutError:
                log.warning(
                    "producer flush did not finish in %.0fs; shutting down anyway", STOP_TIMEOUT_S
                )

    async def send(
        self,
        topic: str,
        value: bytes,
        *,
        key: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Publish and wait for the broker acknowledgement.

        Raises ``KafkaError`` on a broker error and ``TimeoutError`` if no acknowledgement
        arrives within ``delivery_timeout_s`` (aiokafka otherwise keeps retrying while the
        broker is down, which would hang the outbox relay and every consumer's output path).
        A timed-out message may still be delivered later: callers retry, and consumers dedupe
        on ``event_id`` (at-least-once).
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._delivery_timeout_s
        # phase 1: queue the record (waits for topic metadata); phase 2: wait for the broker ack
        delivered = await asyncio.wait_for(
            self._producer.send(topic, value=value, key=key, headers=encode_headers(headers or {})),
            self._delivery_timeout_s,
        )
        try:
            # shield: a timeout must not cancel the batch aiokafka already queued
            await asyncio.wait_for(asyncio.shield(delivered), max(deadline - loop.time(), 0.001))
        except TimeoutError:
            delivered.add_done_callback(lambda f: f.cancelled() or f.exception())  # consume
            raise

    async def publish(self, envelope: AnyEnvelope) -> None:
        """Publish a domain event to its topic, keyed per the topic's rule."""
        await self.send(
            envelope.topic.value,
            envelope.to_json_bytes(),
            key=envelope.partition_key().encode("utf-8"),
        )
