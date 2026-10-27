"""EVAL-03b acceptance against the running compose stack (real Kafka, Postgres, DeepSeek).

Seeds one synthetic run with ONE call, publishes ``call.completed`` for it twice (a duplicate
delivery), waits for the ``evaluator`` and ``finalizer`` worker containers, then prints what the
database and the topics contain. Exactly one real judge call is made.

    PYTHONPATH=backend DATABASE_URL=postgresql://pareeksha:pareeksha@localhost:55432/pareeksha \
    KAFKA_BOOTSTRAP_SERVERS=localhost:9094 python proof/EVAL-03b/acceptance.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

import psycopg

from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import CallCompleted, make_envelope
from pareeksha.events.topics import Topics
from tests.integration.eval_support import seed_run
from tests.integration.support import read_topic

URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
BOOTSTRAP = os.environ["KAFKA_BOOTSTRAP_SERVERS"]


def q(sql: str, *params: object) -> list[tuple[object, ...]]:
    with psycopg.connect(URL, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def show(title: str, sql: str, *params: object) -> None:
    print(f"\n-- {title}\n   {' '.join(sql.split())}")
    for row in q(sql, *params):
        print("  ", row)


async def main() -> None:
    (call,) = seed_run(URL, 1)
    print(f"seeded run {call.run_id} item {call.run_item_id} call {call.call_id}")
    envelope = make_envelope(
        CallCompleted(
            call_id=call.call_id,
            source="simulation",
            agent_id=call.agent_id,
            run_id=call.run_id,
            run_item_id=call.run_item_id,
            end_reason="goal_achieved",
        ),
        producer="acceptance",
        correlation_id=str(call.run_id),
    )
    producer = EventProducer(BOOTSTRAP, client_id="acceptance")
    await producer.start()
    await producer.publish(envelope)
    await producer.publish(envelope)  # duplicate delivery of the same event_id
    await producer.stop()
    print(f"published call.completed event_id={envelope.event_id} twice")

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if q("SELECT finished_at FROM test_runs WHERE id = %s", call.run_id)[0][0] is not None:
            break
        await asyncio.sleep(1)
    else:
        raise SystemExit("run did not complete within 180 s")
    await asyncio.sleep(5)  # let the duplicate finish too

    cid, rid = call.call_id, call.run_id
    print("\n=== database ===")
    show(
        "evaluations rows for the call (must be 1)",
        "SELECT count(*) FROM evaluations WHERE call_id = %s",
        cid,
    )
    show(
        "the evaluation",
        "SELECT e.id, rv.version, e.status, e.judge_model, e.temperature, "
        "left(e.prompt_hash, 15), e.overall_score, e.passed, e.critical_failure, "
        "e.needs_human_review, e.failure_types, e.input_tokens, e.output_tokens "
        "FROM evaluations e JOIN rubric_versions rv ON rv.id = e.rubric_version_id "
        "WHERE e.call_id = %s",
        cid,
    )
    show(
        "api_usage rows for the call (one per real judge call)",
        "SELECT provider, operation, units, unit_type, est_cost, cached, run_id = %s AS run_ok "
        "FROM api_usage WHERE call_id = %s",
        rid,
        cid,
    )
    show(
        "processed_events (one row per consumer group)",
        "SELECT consumer_group, count(*) FROM processed_events GROUP BY 1 ORDER BY 1",
    )
    show(
        "deterministic_checks",
        "SELECT check_type, check_key, passed FROM deterministic_checks "
        "WHERE call_id = %s ORDER BY 1, 2",
        cid,
    )
    show("run item", "SELECT status FROM run_items WHERE id = %s", call.run_item_id)
    show(
        "test run",
        "SELECT status, finished_at IS NOT NULL AS finished, summary FROM test_runs WHERE id = %s",
        rid,
    )
    show("dead letters (must be none)", "SELECT count(*) FROM dead_letters")

    print("\n=== topics ===")
    for topic, key in ((Topics.EVALUATION_COMPLETED, str(cid)), (Topics.RUN_COMPLETED, str(rid))):
        msgs = await read_topic(topic, key=key)
        ids = [json.loads(m.value)["event_id"] for m in msgs]
        print(f"{topic.value} key={key}: {len(msgs)} message(s), distinct event_ids={len(set(ids))}")
        for i in ids:
            print("  event_id", i)
    print(f"expected run.completed id = uuid5(run_id, 'run.completed') = {uuid.uuid5(rid, 'run.completed')}")


if __name__ == "__main__":
    asyncio.run(main())
