"""Demo consumer for the INFRA-02 proof: a handler that always fails with a retryable error.

Run on the host against the compose stack, next to the real ``retrier`` and ``dlq-recorder``
containers, to show retry.30s -> retry.5m -> DLQ with the real contract delays:

    PYTHONPATH=backend KAFKA_BOOTSTRAP_SERVERS=localhost:9094 \
    DATABASE_URL=postgresql+psycopg://pareeksha:pareeksha@localhost:55432/pareeksha \
    python proof/INFRA-02/demo_consumer.py
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pareeksha.events.consumer import Ctx, Outgoing, RetryableError, consumer, run_worker
from pareeksha.events.topics import Topics

GROUP = "demo-flaky"


@consumer(group=GROUP, topic=Topics.AUDIT_REQUESTED)
async def handle(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"{stamp} DEMO handler call: event_id={env.event_id} attempt={env.attempt}", flush=True)
    raise RetryableError("agent unreachable (demo)")


if __name__ == "__main__":
    asyncio.run(run_worker(GROUP))
