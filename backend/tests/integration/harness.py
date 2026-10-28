"""Run a consumer (and optionally the retrier and DLQ recorder) in-process on the real broker."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from pareeksha.events.consumer import ConsumerRunner, ConsumerSpec, RetryPolicy
from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import AnyEnvelope
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
from pareeksha.workers.dlq_recorder import DlqRecorder
from pareeksha.workers.retrier import Retrier
from tests.integration.support import SETTINGS, prime_group, unique_group


@dataclass
class Pipeline:
    runner: ConsumerRunner
    producer: EventProducer
    retrier: Retrier | None
    recorder: DlqRecorder | None
    retrier_group: str
    recorder_group: str

    async def send(self, envelope: AnyEnvelope) -> None:
        await self.producer.publish(envelope)

    async def send_raw(
        self, topic: Topics, value: bytes, *, key: str, headers: dict[str, str] | None = None
    ) -> None:
        await self.producer.send(topic.value, value, key=key.encode(), headers=headers)


@contextlib.asynccontextmanager
async def pipeline(
    spec: ConsumerSpec,
    *,
    policy: RetryPolicy | None = None,
    with_retrier: bool = True,
    with_recorder: bool = True,
    settings: EventSettings = SETTINGS,
) -> AsyncIterator[Pipeline]:
    """Start the consumer for ``spec`` (+ retrier, + dlq-recorder) with fresh, primed groups.

    ``settings`` points the workers at another database (the planner tests use the migrated one).
    """
    retrier_group = unique_group("retrier")
    recorder_group = unique_group("dlq-recorder")
    await prime_group(spec.group, list(spec.topics))
    if with_retrier:
        await prime_group(retrier_group, [Topics.RETRY_30S, Topics.RETRY_5M])
    if with_recorder:
        await prime_group(recorder_group, [Topics.DLQ])

    producer = EventProducer(settings.bootstrap_servers, client_id="test-producer")
    await producer.start()
    runner = ConsumerRunner(spec, settings, policy=policy)
    retrier = Retrier(settings, group=retrier_group) if with_retrier else None
    recorder = DlqRecorder(settings, group=recorder_group) if with_recorder else None
    components: list[Any] = [c for c in (runner, retrier, recorder) if c is not None]
    tasks = [asyncio.create_task(c.run()) for c in components]
    try:
        for c in components:
            await c.wait_ready()
        yield Pipeline(runner, producer, retrier, recorder, retrier_group, recorder_group)
    finally:
        for c in components:
            c.stop_event.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await producer.stop()
        for r in results:
            if isinstance(r, BaseException):
                raise r
