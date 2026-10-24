"""The retry chain with the real contract delays (30 s, then 5 min) on the real broker.

Takes about 5.5 minutes by design: it is the evidence that the retrier honours ``retry.30s`` and
``retry.5m`` without being kicked out of its consumer group while it waits.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

from pareeksha.events.consumer import ConsumerSpec, Ctx, Outgoing, RetryableError
from pareeksha.events.topics import Topics
from tests.integration.harness import pipeline
from tests.integration.support import (
    audit_envelope,
    db,
    group_lag,
    read_topic,
    unique_group,
    wait_for,
)

AUDIT = Topics.AUDIT_REQUESTED


async def test_three_failures_with_real_30s_and_5m_delays_end_in_the_dlq() -> None:
    group = unique_group("real-delays")
    env = audit_envelope()
    key = str(env.payload.call_id)
    calls: list[tuple[int, float]] = []

    async def handle(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        calls.append((e.attempt, time.monotonic()))
        raise RetryableError("agent unreachable")

    spec = ConsumerSpec(group=group, topics=(AUDIT,), handler=handle)
    async with pipeline(spec) as p:  # default RetryPolicy = the contract (30 s / 5 min)
        await p.send(env)

        async def dead() -> Any:
            with db() as conn:
                return conn.execute(
                    "SELECT attempts, status FROM dead_letters WHERE event_id = %s", (env.event_id,)
                ).fetchone()

        row = await wait_for(dead, timeout=420, interval=2, what="dead letter after 30s + 5m")
        lag = await group_lag(group, [AUDIT])

    attempts = [a for a, _ in calls]
    gaps = [calls[1][1] - calls[0][1], calls[2][1] - calls[1][1]]
    assert attempts == [1, 2, 3]
    assert 30 <= gaps[0] < 45, gaps
    assert 300 <= gaps[1] < 315, gaps
    assert tuple(row) == (3, "open")
    assert all(v == 0 for v in lag.values())
    (dlq,) = await read_topic(Topics.DLQ, key=key)
    assert json.loads(dlq.value)["attempt"] == 3
