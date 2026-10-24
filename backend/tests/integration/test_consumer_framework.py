"""Consumer framework against a real Kafka broker and Postgres (INFRA-02 acceptance).

Covers: duplicate delivery -> one side effect; retry then success; 3 failures -> retry.30s ->
retry.5m -> DLQ (+ dead_letters row); permanent error -> DLQ; unparseable messages -> DLQ;
throttle keeps the attempt; retry copies are only processed by the group that failed; output
event ids are deterministic. Retry delays are scaled down here; tests/integration/test_real_delays
runs the same chain with the real 30 s and 5 min delays.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Sequence
from typing import Any

from pareeksha.events.consumer import (
    ConsumerSpec,
    Ctx,
    Outgoing,
    PermanentError,
    RetryableError,
    RetryPolicy,
    Throttled,
)
from pareeksha.events.runtime import HEADER_CONSUMER_GROUP
from pareeksha.events.topics import (
    HEADER_ERROR,
    HEADER_NOT_BEFORE,
    HEADER_REASON,
    HEADER_TARGET_TOPIC,
    Topics,
)
from tests.integration.harness import Pipeline, pipeline
from tests.integration.support import (
    audit_envelope,
    completed_payload,
    db,
    group_lag,
    read_topic,
    side_effects,
    unique_group,
    wait_for,
)

FAST = RetryPolicy(delay_seconds={2: 0.5, 3: 1.5}, throttle_delay_seconds=0.5)
AUDIT = Topics.AUDIT_REQUESTED


def _spec(group: str, handler: Any, reproduce: Any = None) -> ConsumerSpec:
    return ConsumerSpec(group=group, topics=(AUDIT,), handler=handler, reproduce=reproduce)


async def _insert_side_effect(ctx: Ctx, env: Any) -> None:
    await ctx.tx.execute(
        "INSERT INTO it_side_effects (grp, event_id) VALUES (%s, %s)", (ctx.group, env.event_id)
    )


async def _lag_zero(group: str, topics: list[Topics]) -> bool:
    lag = await group_lag(group, topics)
    return all(v == 0 for v in lag.values())


async def _wait_lag_zero(p: Pipeline, topics: list[Topics]) -> None:
    async def probe() -> bool:
        return await _lag_zero(p.runner.group, topics)

    await wait_for(probe, what=f"zero lag for {p.runner.group}")


def _dead_letter(group: str, event_id: uuid.UUID) -> tuple[Any, ...] | None:
    with db() as conn:
        return conn.execute(
            "SELECT original_topic, key, consumer_group, error, attempts, status FROM dead_letters "
            "WHERE event_id = %s AND consumer_group = %s",
            (event_id, group),
        ).fetchone()


def _processed(group: str, event_id: uuid.UUID) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT count(*) FROM processed_events WHERE consumer_group = %s AND event_id = %s",
            (group, event_id),
        ).fetchone()
    assert row is not None
    return int(row[0])


async def test_duplicate_delivery_gives_one_side_effect() -> None:
    group = unique_group("dup")
    env = audit_envelope()
    call_id = env.payload.call_id
    calls: list[uuid.UUID] = []

    async def handle(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        calls.append(e.event_id)
        await _insert_side_effect(ctx, e)
        return [Outgoing(completed_payload(call_id))]

    async def reproduce(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        assert ctx.duplicate
        return [Outgoing(completed_payload(call_id))]

    async with pipeline(
        _spec(group, handle, reproduce), with_retrier=False, with_recorder=False
    ) as p:
        await p.send(env)
        await p.send(env)  # duplicate delivery: same event_id

        async def two_outputs() -> list[Any] | None:
            out = await read_topic(Topics.CALL_COMPLETED, key=str(call_id))
            return out if len(out) >= 2 else None

        outputs = await wait_for(two_outputs, what="output produced for both deliveries")
        await _wait_lag_zero(p, [AUDIT])

    assert calls == [env.event_id], "handler must run once"
    assert side_effects(group, env.event_id) == 1
    assert _processed(group, env.event_id) == 1
    # the re-produced output carries the same deterministic event_id (downstream dedupes on it)
    ids = {json.loads(o.value)["event_id"] for o in outputs}
    assert ids == {str(uuid.uuid5(env.event_id, "call.completed"))}


async def test_retryable_failure_then_success_processes_once() -> None:
    group = unique_group("retry-ok")
    env = audit_envelope()
    attempts: list[int] = []

    async def handle(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        attempts.append(e.attempt)
        await _insert_side_effect(ctx, e)
        if len(attempts) == 1:
            raise RetryableError("temporary 503 from agent")
        return []

    async with pipeline(_spec(group, handle), policy=FAST) as p:
        await p.send(env)
        await wait_for(lambda: _async(side_effects(group, env.event_id) == 1), what="side effect")
        await _wait_lag_zero(p, [AUDIT])

    assert attempts == [1, 2]
    assert side_effects(group, env.event_id) == 1  # the failed attempt's insert was rolled back
    assert _dead_letter(group, env.event_id) is None
    assert len(await read_topic(Topics.DLQ, key=str(env.payload.call_id))) == 0


async def test_three_failures_go_through_retry_30s_and_retry_5m_to_dlq() -> None:
    group = unique_group("fail3")
    env = audit_envelope()
    key = str(env.payload.call_id)
    attempts: list[int] = []
    times: list[float] = []

    async def handle(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        attempts.append(e.attempt)
        times.append(time.monotonic())
        await _insert_side_effect(ctx, e)  # must be rolled back every time
        raise RetryableError("agent unreachable")

    async with pipeline(_spec(group, handle), policy=FAST) as p:
        await p.send(env)
        row = await wait_for(
            lambda: _async(_dead_letter(group, env.event_id)), what="dead_letters row"
        )
        await _wait_lag_zero(p, [AUDIT])
        retrier_lag = await group_lag(p.retrier_group, [Topics.RETRY_30S, Topics.RETRY_5M])
        recorder_lag = await group_lag(p.recorder_group, [Topics.DLQ])

    assert attempts == [1, 2, 3]
    assert times[1] - times[0] >= 0.5 and times[2] - times[1] >= 1.5, (
        "retrier must honour the delay"
    )
    assert side_effects(group, env.event_id) == 0
    assert _processed(group, env.event_id) == 0

    r30 = await read_topic(Topics.RETRY_30S, key=key)
    r5m = await read_topic(Topics.RETRY_5M, key=key)
    dlq = await read_topic(Topics.DLQ, key=key)
    assert [json.loads(m.value)["attempt"] for m in r30] == [2]
    assert [json.loads(m.value)["attempt"] for m in r5m] == [3]
    assert [json.loads(m.value)["attempt"] for m in dlq] == [3]
    assert r30[0].headers[HEADER_TARGET_TOPIC] == AUDIT.value
    assert HEADER_NOT_BEFORE in r30[0].headers and HEADER_NOT_BEFORE in r5m[0].headers
    assert "agent unreachable" in dlq[0].headers[HEADER_ERROR]
    assert dlq[0].headers[HEADER_CONSUMER_GROUP] == group

    original_topic, rkey, consumer_group, error, n_attempts, status = row
    assert (original_topic, rkey, consumer_group, n_attempts, status) == (
        AUDIT.value,
        key,
        group,
        3,
        "open",
    )
    assert "agent unreachable" in error
    assert all(v == 0 for v in {**retrier_lag, **recorder_lag}.values()), (
        retrier_lag,
        recorder_lag,
    )


async def test_permanent_error_goes_straight_to_dlq() -> None:
    group = unique_group("perm")
    env = audit_envelope()
    key = str(env.payload.call_id)
    attempts: list[int] = []

    async def handle(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        attempts.append(e.attempt)
        raise PermanentError("agent rejected the call: 400 bad request")

    async with pipeline(_spec(group, handle), policy=FAST) as p:
        await p.send(env)
        row = await wait_for(
            lambda: _async(_dead_letter(group, env.event_id)), what="dead_letters row"
        )
        await _wait_lag_zero(p, [AUDIT])

    assert attempts == [1]
    assert row[4] == 1
    assert await read_topic(Topics.RETRY_30S, key=key) == []
    assert await read_topic(Topics.RETRY_5M, key=key) == []
    assert len(await read_topic(Topics.DLQ, key=key)) == 1


async def test_unparseable_and_unknown_type_messages_go_to_dlq() -> None:
    group = unique_group("poison")
    calls: list[Any] = []

    async def handle(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        calls.append(e)
        return []

    garbage_key = f"garbage-{uuid.uuid4()}"
    unknown_key = f"unknown-{uuid.uuid4()}"
    unknown_event_id = uuid.uuid4()
    unknown = {
        "event_id": str(unknown_event_id),
        "type": "nonsense.happened",
        "version": 1,
        "occurred_at": "2026-10-24T10:00:00Z",
        "correlation_id": "x",
        "attempt": 1,
        "producer": "t@h",
        "payload": {},
    }
    async with pipeline(_spec(group, handle), policy=FAST, with_retrier=False) as p:
        await p.send_raw(AUDIT, b"{not json", key=garbage_key)
        await p.send_raw(AUDIT, json.dumps(unknown).encode(), key=unknown_key)

        async def both_recorded() -> list[Any] | None:
            with db() as conn:
                rows = conn.execute(
                    "SELECT key, envelope, error FROM dead_letters WHERE consumer_group = %s "
                    "ORDER BY key",
                    (group,),
                ).fetchall()
            return rows if len(rows) == 2 else None

        rows = await wait_for(both_recorded, what="two dead letters")
        await _wait_lag_zero(p, [AUDIT])

    assert calls == []
    by_key = {r[0]: r for r in rows}
    assert by_key[garbage_key][1] == {"raw": "{not json"}
    assert by_key[unknown_key][1]["event_id"] == str(unknown_event_id)
    assert "nonsense.happened" in by_key[unknown_key][2]


async def test_throttle_does_not_consume_attempts() -> None:
    group = unique_group("throttle")
    env = audit_envelope()
    key = str(env.payload.call_id)
    attempts: list[int] = []

    async def handle(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        attempts.append(e.attempt)
        if len(attempts) <= 3:  # more throttles than the attempt budget allows failures
            raise Throttled("run at max_concurrency")
        await _insert_side_effect(ctx, e)
        return []

    async with pipeline(_spec(group, handle), policy=FAST) as p:
        await p.send(env)
        await wait_for(
            lambda: _async(side_effects(group, env.event_id) == 1), what="finally processed"
        )
        await _wait_lag_zero(p, [AUDIT])

    assert attempts == [1, 1, 1, 1], "attempt must stay 1 while throttled"
    r30 = await read_topic(Topics.RETRY_30S, key=key)
    assert len(r30) == 3
    assert all(m.headers[HEADER_REASON] == "throttled" for m in r30)
    assert all(json.loads(m.value)["attempt"] == 1 for m in r30)
    assert await read_topic(Topics.RETRY_5M, key=key) == []
    assert await read_topic(Topics.DLQ, key=key) == []
    assert _dead_letter(group, env.event_id) is None


async def test_copy_for_another_group_is_skipped_but_committed() -> None:
    group = unique_group("only-mine")
    seen: list[uuid.UUID] = []

    async def handle(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        seen.append(e.event_id)
        return []

    foreign = audit_envelope()
    mine = audit_envelope()
    async with pipeline(_spec(group, handle), with_retrier=False, with_recorder=False) as p:
        await p.send_raw(
            AUDIT,
            foreign.to_json_bytes(),
            key=str(foreign.payload.call_id),
            headers={HEADER_CONSUMER_GROUP: "some-other-group"},
        )
        await p.send(mine)
        await wait_for(lambda: _async(bool(seen)), what="own message processed")
        await _wait_lag_zero(p, [AUDIT])

    assert seen == [mine.event_id]


async def test_output_event_ids_are_deterministic_and_discriminated() -> None:
    group = unique_group("outputs")
    env = audit_envelope()
    call_a, call_b = uuid.uuid4(), uuid.uuid4()

    async def handle(e: Any, ctx: Ctx) -> Sequence[Outgoing]:
        return [
            Outgoing(completed_payload(call_a), discriminator="a"),
            Outgoing(completed_payload(call_b), discriminator="b", correlation_id="custom-corr"),
        ]

    async with pipeline(_spec(group, handle), with_retrier=False, with_recorder=False) as p:
        await p.send(env)

        async def both() -> bool:
            return bool(await read_topic(Topics.CALL_COMPLETED, key=str(call_a))) and bool(
                await read_topic(Topics.CALL_COMPLETED, key=str(call_b))
            )

        await wait_for(both, what="both outputs")

    (out_a,) = [
        json.loads(m.value) for m in await read_topic(Topics.CALL_COMPLETED, key=str(call_a))
    ]
    (out_b,) = [
        json.loads(m.value) for m in await read_topic(Topics.CALL_COMPLETED, key=str(call_b))
    ]
    assert out_a["event_id"] == str(uuid.uuid5(env.event_id, "call.completed:a"))
    assert out_b["event_id"] == str(uuid.uuid5(env.event_id, "call.completed:b"))
    assert out_a["causation_id"] == str(env.event_id)
    assert out_a["correlation_id"] == env.correlation_id
    assert out_b["correlation_id"] == "custom-corr"
    assert out_a["producer"].startswith(f"{group}@")


async def _async(value: Any) -> Any:
    return value
