"""T-NFR-4c: two instances of one consumer group share the partitions with no configuration
change; when one leaves, the other takes over; every event is handled exactly once."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Any

import pytest

from pareeksha.events.consumer import ConsumerRunner, Ctx, Outgoing
from pareeksha.events.producer import EventProducer
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
from tests.kafka.kit import (
    BOOTSTRAP,
    call_completed,
    lag_is_zero,
    prime_group,
    scalar,
    seed_calls,
    settings_for,
    spec_for,
    unique,
    wait_for,
)

IN = Topics.CALL_COMPLETED
PARTITIONS = 6


@pytest.fixture
def settings(database_url: str) -> EventSettings:
    return settings_for(database_url)


def assignment(runner: ConsumerRunner) -> set[int]:
    return {tp.partition for tp in runner._consumer.assignment()}


async def test_two_instances_share_the_partitions_and_handle_each_event_once(
    settings: EventSettings,
) -> None:
    group = unique("scale")
    calls = seed_calls(settings, 40)
    handled: Counter[uuid.UUID] = Counter()
    by_instance: dict[str, int] = {"a": 0, "b": 0}

    def handler_for(name: str) -> Any:
        async def handle(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
            by_instance[name] += 1
            handled[env.payload.call_id] += 1
            return []

        return handle

    await prime_group(group, [IN])
    a = ConsumerRunner(spec_for(group, IN, handler_for("a")), settings)
    b = ConsumerRunner(spec_for(group, IN, handler_for("b")), settings)  # same spec, same settings
    producer = EventProducer(BOOTSTRAP, client_id="qa-scale")
    await producer.start()
    task_a = asyncio.create_task(a.run())
    await a.wait_ready()
    task_b = asyncio.create_task(b.run())
    await b.wait_ready()
    try:

        async def split() -> bool:
            pa, pb = assignment(a), assignment(b)
            return bool(pa) and bool(pb) and not (pa & pb) and len(pa | pb) == PARTITIONS

        await wait_for(split, timeout=60, what="partitions split between the two instances")

        for call_id in calls[:30]:
            await producer.publish(call_completed(call_id))

        async def first_batch_done() -> bool:
            return sum(handled.values()) == 30 and await lag_is_zero(group, [IN])

        await wait_for(first_batch_done, timeout=60, what="30 events handled")
        assert by_instance["a"] > 0 and by_instance["b"] > 0, by_instance  # both did work
        assert by_instance["a"] + by_instance["b"] == 30

        b.stop()  # scale down: instance a must take over every partition
        await asyncio.wait_for(task_b, 30)

        async def a_owns_all() -> bool:
            return assignment(a) == set(range(PARTITIONS))

        await wait_for(a_owns_all, timeout=60, what="instance a to take over all partitions")
        before = by_instance["a"]
        for call_id in calls[30:]:
            await producer.publish(call_completed(call_id))

        async def second_batch_done() -> bool:
            return sum(handled.values()) == 40 and await lag_is_zero(group, [IN])

        await wait_for(second_batch_done, timeout=60, what="the remaining 10 events handled")
        assert by_instance["a"] - before == 10
    finally:
        a.stop()
        b.stop()
        await asyncio.gather(task_a, task_b, return_exceptions=True)
        await producer.stop()
    assert set(handled) == set(calls) and set(handled.values()) == {1}
    done = scalar(
        settings,
        "SELECT count(*) FROM processed_events WHERE consumer_group = %s",
        group,
    )
    assert done == 40  # one processed_events row per event across both instances
