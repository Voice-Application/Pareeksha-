"""Retrier and DLQ-recorder edge cases against the real broker."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pareeksha.events.consumer import ConsumerSpec
from pareeksha.events.runtime import HEADER_CONSUMER_GROUP, utc_iso
from pareeksha.events.topics import (
    HEADER_ERROR,
    HEADER_NOT_BEFORE,
    HEADER_TARGET_TOPIC,
    Topics,
)
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


async def _noop(env: Any, ctx: Any) -> list[Any]:
    return []


def _spec() -> ConsumerSpec:
    # a consumer on a topic nobody writes to; these tests only need the retrier and the recorder
    return ConsumerSpec(group=unique_group("idle"), topics=(Topics.PROGRESS,), handler=_noop)


async def test_retrier_pauses_until_not_before_then_redelivers_with_group_header() -> None:
    env = audit_envelope()
    key = str(env.payload.call_id)
    due = datetime.now(UTC) + timedelta(seconds=3)
    async with pipeline(_spec(), with_recorder=False) as p:
        sent = time.monotonic()
        await p.send_raw(
            Topics.RETRY_30S,
            env.to_json_bytes(),
            key=key,
            headers={
                HEADER_TARGET_TOPIC: AUDIT.value,
                HEADER_NOT_BEFORE: utc_iso(due),
                HEADER_CONSUMER_GROUP: "evaluator",
                HEADER_ERROR: "boom",
            },
        )

        async def delivered() -> list[Any]:
            return await read_topic(AUDIT, key=key)

        (msg,) = await wait_for(delivered, what="message redelivered to its topic")
        waited = time.monotonic() - sent
        retrier_group = p.retrier_group
        lag = await group_lag(retrier_group, [Topics.RETRY_30S, Topics.RETRY_5M])

    assert waited >= 2.5, f"delivered after only {waited:.1f}s, before x-not-before"
    assert msg.value == env.to_json_bytes()
    assert msg.headers == {HEADER_CONSUMER_GROUP: "evaluator", HEADER_ERROR: "boom"}
    assert HEADER_NOT_BEFORE not in msg.headers and HEADER_TARGET_TOPIC not in msg.headers
    assert all(v == 0 for v in lag.values()), lag


async def test_retry_message_without_target_topic_is_parked_in_the_dlq() -> None:
    key = f"misrouted-{uuid.uuid4()}"
    async with pipeline(_spec()) as p:
        body = json.dumps({"hello": key}).encode()  # unique: identical garbage dedupes by content
        await p.send_raw(Topics.RETRY_5M, body, key=key)

        def row() -> Any:
            with db() as conn:
                return conn.execute(
                    "SELECT consumer_group, error, envelope FROM dead_letters WHERE key = %s",
                    (key,),
                ).fetchone()

        async def recorded() -> Any:
            return row()

        got = await wait_for(recorded, what="misrouted message recorded as dead letter")
    assert got[0] == "unknown" and "x-target-topic" in got[1] and got[2] == {"hello": key}
    assert len(await read_topic(Topics.DLQ, key=key)) == 1


async def test_recorder_is_idempotent_and_reopens_replayed_letters_only() -> None:
    group = unique_group("replayed")
    replayed, discarded = audit_envelope(), audit_envelope()
    with db() as conn:
        for env, status in ((replayed, "replayed"), (discarded, "discarded")):
            conn.execute(
                "INSERT INTO dead_letters (event_id, original_topic, key, consumer_group, "
                "envelope, "
                "error, attempts, status) VALUES (%s, %s, %s, %s, %s, 'old', 3, %s)",
                (
                    env.event_id,
                    AUDIT.value,
                    str(env.payload.call_id),
                    group,
                    json.dumps(env.model_dump(mode="json")),
                    status,
                ),
            )
    headers = {
        HEADER_TARGET_TOPIC: AUDIT.value,
        HEADER_CONSUMER_GROUP: group,
        HEADER_ERROR: "failed again",
    }
    async with pipeline(_spec(), with_retrier=False) as p:
        for env in (replayed, replayed, discarded):  # replayed twice = duplicate DLQ delivery
            await p.send_raw(
                Topics.DLQ, env.to_json_bytes(), key=str(env.payload.call_id), headers=headers
            )

        async def settled() -> bool:
            assert p.recorder is not None
            return p.recorder.recorded == 3

        await wait_for(settled, what="recorder consumed all three")

    with db() as conn:
        rows = dict(
            conn.execute(
                "SELECT event_id, status || '|' || error FROM dead_letters "
                "WHERE consumer_group = %s",
                (group,),
            ).fetchall()
        )
    assert rows[replayed.event_id] == "open|failed again"
    assert rows[discarded.event_id] == "discarded|old", "an operator's discard must stick"
