"""T-FR-RN-9: three failures go retry.30s -> retry.5m -> DLQ (one dead_letters row); a throttle
never reaches the DLQ and never consumes an attempt.

Real Kafka and the Alembic-built tables. The retry delays are scaled down by the framework's own
``RetryPolicy`` (0.5 s / 1 s); the real 30 s / 5 min waits are measured by
``tests/integration/test_real_delays.py`` and ``proof/INFRA-02/demo.txt``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import pytest

from pareeksha.events.consumer import Ctx, Outgoing, RetryableError, Throttled
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import (
    HEADER_ERROR,
    HEADER_NOT_BEFORE,
    HEADER_REASON,
    HEADER_TARGET_TOPIC,
    REASON_THROTTLED,
    Topics,
)
from tests.kafka.kit import (
    FAST,
    call_completed,
    consumer,
    evaluate,
    evaluation_count,
    lag_is_zero,
    read_topic,
    scalar,
    seed_calls,
    settings_for,
    spec_for,
    unique,
    wait_for,
)

IN = Topics.CALL_COMPLETED


@pytest.fixture
def settings(database_url: str) -> EventSettings:
    return settings_for(database_url)


def attempts_in(messages: list[Any]) -> list[int]:
    return [json.loads(m.value)["attempt"] for m in messages]


async def test_three_failures_walk_the_retry_topics_into_one_dead_letter(
    settings: EventSettings,
) -> None:
    [call_id] = seed_calls(settings)
    key = str(call_id)
    group = unique("fail3")
    env = call_completed(call_id)
    seen: list[tuple[int, float]] = []

    async def always_fails(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        seen.append((e.attempt, time.monotonic()))
        await evaluate(e, ctx)  # a real INSERT that must be rolled back every time
        raise RetryableError("judge provider returned 503")

    async with consumer(
        settings, spec_for(group, IN, always_fails), policy=FAST, with_retry_path=True
    ) as c:
        await c.send(env)

        async def letter() -> Any:
            return scalar(
                settings,
                "SELECT attempts FROM dead_letters WHERE event_id = %s AND consumer_group = %s",
                env.event_id,
                group,
            )

        assert await wait_for(letter, timeout=60, what="the dead_letters row") == 3
        await wait_for(lambda: lag_is_zero(group, [IN]), what="consumer lag zero")
        assert c.retrier_group and c.recorder_group
        await wait_for(
            lambda: lag_is_zero(c.retrier_group or "", [Topics.RETRY_30S, Topics.RETRY_5M]),
            what="retrier lag zero",
        )
        await wait_for(lambda: lag_is_zero(c.recorder_group or "", [Topics.DLQ]), what="dlq lag")

    assert [a for a, _ in seen] == [1, 2, 3]
    assert seen[1][1] - seen[0][1] >= 0.5 and seen[2][1] - seen[1][1] >= 1.0  # delays honoured
    assert evaluation_count(settings, call_id) == 0  # no attempt left a row behind
    assert (
        scalar(settings, "SELECT count(*) FROM processed_events WHERE event_id = %s", env.event_id)
        == 0
    )

    r30 = await read_topic(Topics.RETRY_30S, key=key)
    r5m = await read_topic(Topics.RETRY_5M, key=key)
    dlq = await read_topic(Topics.DLQ, key=key)
    assert attempts_in(r30) == [2] and attempts_in(r5m) == [3] and attempts_in(dlq) == [3]
    assert r30[0].headers[HEADER_TARGET_TOPIC] == IN.value
    assert HEADER_NOT_BEFORE in r30[0].headers and HEADER_NOT_BEFORE in r5m[0].headers
    assert "503" in dlq[0].headers[HEADER_ERROR]

    row = scalar(
        settings,
        "SELECT status FROM dead_letters WHERE event_id = %s AND consumer_group = %s",
        env.event_id,
        group,
    )
    assert row == "open"
    count = scalar(
        settings,
        "SELECT count(*) FROM dead_letters WHERE event_id = %s AND consumer_group = %s",
        env.event_id,
        group,
    )
    assert count == 1  # exactly one row, however many times the DLQ message is delivered


async def test_a_permanent_error_skips_the_retry_topics(settings: EventSettings) -> None:
    [call_id] = seed_calls(settings)
    group = unique("perm")
    env = call_completed(call_id)

    async def bad_data(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        raise ValueError("schema violation in payload")

    async with consumer(settings, spec_for(group, IN, bad_data), with_retry_path=True) as c:
        await c.send(env)

        async def letter() -> Any:
            return scalar(
                settings,
                "SELECT attempts FROM dead_letters WHERE event_id = %s AND consumer_group = %s",
                env.event_id,
                group,
            )

        assert await wait_for(letter, what="the dead_letters row") == 1
    key = str(call_id)
    assert await read_topic(Topics.RETRY_30S, key=key) == []
    assert await read_topic(Topics.RETRY_5M, key=key) == []
    assert len(await read_topic(Topics.DLQ, key=key)) == 1


async def test_throttling_never_reaches_the_dlq_and_never_uses_an_attempt(
    settings: EventSettings,
) -> None:
    [call_id] = seed_calls(settings)
    key = str(call_id)
    group = unique("throttle")
    env = call_completed(call_id)
    seen: list[int] = []

    async def at_the_run_cap(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        seen.append(e.attempt)
        if len(seen) <= 3:  # no free run slot: wait without burning the retry budget
            raise Throttled("run is at max_concurrency")
        return await evaluate(e, ctx)

    async with consumer(
        settings, spec_for(group, IN, at_the_run_cap), policy=FAST, with_retry_path=True
    ) as c:
        await c.send(env)

        async def evaluated() -> bool:
            return evaluation_count(settings, call_id) == 1

        await wait_for(evaluated, timeout=60, what="the evaluation after the slot frees")
        await wait_for(lambda: lag_is_zero(group, [IN]), what="consumer lag zero")
        assert c.retrier_group
        await wait_for(
            lambda: lag_is_zero(c.retrier_group or "", [Topics.RETRY_30S]), what="retrier lag zero"
        )
    assert seen == [1, 1, 1, 1]  # the attempt counter never moved
    r30 = await read_topic(Topics.RETRY_30S, key=key)
    assert len(r30) == 3 and attempts_in(r30) == [1, 1, 1]
    assert all(m.headers[HEADER_REASON] == REASON_THROTTLED for m in r30)
    assert await read_topic(Topics.RETRY_5M, key=key) == []
    assert await read_topic(Topics.DLQ, key=key) == []
    assert (
        scalar(settings, "SELECT count(*) FROM dead_letters WHERE event_id = %s", env.event_id) == 0
    )
