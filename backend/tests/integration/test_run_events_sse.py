"""GET /runs/{id}/events: snapshot, live progress, reconnect with Last-Event-ID (API-04).

Real Postgres, real Kafka: events are produced to ``pareeksha.progress.v1`` exactly as the workers
do and read back through the stream. Unit tests of the id encoding are at the bottom.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import AsyncClient

from pareeksha.api.errors import ApiError
from pareeksha.api.main import app
from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import ProgressEvent, make_envelope
from pareeksha.events.settings import kafka_bootstrap
from pareeksha.runs.stream import ProgressStream, decode_cursor, encode_cursor
from tests.conftest import Tenant, new_tenant
from tests.integration.api04_support import Factory, SeededRun, seed_run
from tests.integration.runs_support import API
from tests.integration.support import BOOTSTRAP


@pytest.fixture(autouse=True)
def _broker() -> Iterator[None]:
    app.dependency_overrides[kafka_bootstrap] = lambda: BOOTSTRAP
    yield
    app.dependency_overrides.pop(kafka_bootstrap, None)


@pytest.fixture
async def producer() -> AsyncIterator[EventProducer]:
    p = EventProducer(BOOTSTRAP)
    await p.start()
    yield p
    await p.stop()


def _event(run_id: uuid.UUID, **fields: Any) -> Any:
    return make_envelope(
        ProgressEvent(run_id=run_id, **fields), producer="test", correlation_id="c"
    )


def item_status(run_id: uuid.UUID, item: uuid.UUID, status: str) -> Any:
    return _event(
        run_id, kind="item.status", run_item_id=item, status=status, scenario="S", persona="P"
    )


def run_completed(run_id: uuid.UUID) -> Any:
    return _event(run_id, kind="run.completed", pass_rate=0.5, critical_failures=1)


def parse_sse(chunks: list[str]) -> list[dict[str, Any]]:
    """``[{id, event, data}, ...]`` for the event chunks; heartbeats come back as ``comment``."""
    out: list[dict[str, Any]] = []
    for chunk in chunks:
        if chunk.startswith(":"):
            out.append({"comment": chunk.strip()})
            continue
        fields = dict(line.split(": ", 1) for line in chunk.strip().split("\n"))
        out.append(
            {"id": fields["id"], "event": fields["event"], "data": json.loads(fields["data"])}
        )
    return out


async def collect(stream: ProgressStream, *, timeout: float = 20.0) -> list[str]:
    async def run() -> list[str]:
        return [chunk async for chunk in stream.events()]

    return await asyncio.wait_for(run(), timeout)


async def running_run(api: AsyncClient, tenant: Tenant, factory: Factory) -> SeededRun:
    return await seed_run(api, factory, tenant, scores=[(88, True), None], status="running")


# ---------------------------------------------------------------------------------- live


async def test_snapshot_then_live_events_of_this_run_only_until_run_completed(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, producer: EventProducer
) -> None:
    run = await running_run(api, tenant, session_factory)
    other = await running_run(api, tenant, session_factory)
    stream = ProgressStream(
        BOOTSTRAP, session_factory, tenant.project_id, run.run_id, heartbeat_s=60
    )
    await stream.open()
    task = asyncio.create_task(collect(stream))

    queued, evaluated = run.item_ids[1], run.item_ids[0]
    await producer.publish(item_status(run.run_id, queued, "in_progress"))
    await producer.publish(item_status(other.run_id, other.item_ids[1], "in_progress"))  # not ours
    await producer.publish(
        _event(
            run.run_id,
            kind="call.evaluated",
            call_id=run.calls[0].call_id,
            overall_score=72.5,
            passed=False,
            critical_failure=True,
        )  # no run_item_id: the stream looks it up from the call
    )
    await producer.publish(run_completed(other.run_id))  # another run finishing does not end ours
    await producer.publish(run_completed(run.run_id))
    events = parse_sse(await task)

    assert [e["event"] for e in events] == [
        "snapshot", "item.status", "call.evaluated", "run.completed",
    ]  # fmt: skip
    snapshot = events[0]["data"]
    assert snapshot["run"]["id"] == str(run.run_id) and snapshot["run"]["status"] == "running"
    assert snapshot["run"]["progress"]["total"] == 2
    by_id = {i["id"]: i for i in snapshot["items"]}
    assert (
        by_id[str(evaluated)]["overall_score"] == 88.0 and by_id[str(queued)]["status"] == "queued"
    )
    assert events[1]["data"] == {
        "run_item_id": str(queued), "status": "in_progress", "scenario": "S", "persona": "P",
    }  # fmt: skip
    assert events[2]["data"] == {
        "run_item_id": str(run.calls[0].run_item_id),
        "call_id": str(run.calls[0].call_id),
        "overall_score": 72.5,
        "passed": False,
        "critical_failure": True,
    }
    assert events[3]["data"] == {
        "run_id": str(run.run_id), "summary": {"pass_rate": 0.5, "critical_failures": 1},
    }  # fmt: skip
    # every message carries a resumable id: the last offset read on every partition
    ids = [decode_cursor(e["id"]) for e in events]
    assert all(i is not None and set(i) == set(ids[0] or {}) and len(i) >= 1 for i in ids)


async def test_reconnect_with_last_event_id_replays_exactly_what_was_missed(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, producer: EventProducer
) -> None:
    run = await running_run(api, tenant, session_factory)
    item = run.item_ids[1]

    first = ProgressStream(BOOTSTRAP, session_factory, tenant.project_id, run.run_id)
    await first.open()
    seen: list[str] = []
    stream_iter = first.events()
    seen.append(await anext(stream_iter))  # snapshot
    await producer.publish(item_status(run.run_id, item, "connecting"))
    seen.append(await asyncio.wait_for(anext(stream_iter), 20))
    await stream_iter.aclose()  # the client drops
    events = parse_sse(seen)
    assert [e["event"] for e in events] == ["snapshot", "item.status"]
    last_id = events[-1]["id"]

    # while disconnected: two more events and the end of the run
    await producer.publish(item_status(run.run_id, item, "in_progress"))
    await producer.publish(item_status(run.run_id, item, "completed"))
    await producer.publish(run_completed(run.run_id))

    second = ProgressStream(
        BOOTSTRAP, session_factory, tenant.project_id, run.run_id, last_event_id=last_id
    )
    await second.open()
    again = parse_sse(await collect(second))
    assert [e["event"] for e in again] == [
        "snapshot",
        "item.status",
        "item.status",
        "run.completed",
    ]
    assert [e["data"]["status"] for e in again[1:3]] == ["in_progress", "completed"]

    # an id that is not ours (or none) starts at the end: nothing old is replayed
    third = ProgressStream(
        BOOTSTRAP, session_factory, tenant.project_id, run.run_id, last_event_id="garbage"
    )
    await third.open()
    task = asyncio.create_task(collect(third))
    await producer.publish(run_completed(run.run_id))
    assert [e["event"] for e in parse_sse(await task)] == ["snapshot", "run.completed"]


async def test_a_finished_run_gets_snapshot_and_run_completed_then_the_stream_ends(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    run = await seed_run(
        api, session_factory, tenant, scores=[(90, True)],
        summary={"pass_rate": 1.0, "critical_failures": 0},
    )  # fmt: skip
    stream = ProgressStream(BOOTSTRAP, session_factory, tenant.project_id, run.run_id)
    await stream.open()
    events = parse_sse(await collect(stream, timeout=10))
    assert [e["event"] for e in events] == ["snapshot", "run.completed"]
    assert events[1]["data"]["summary"] == {"pass_rate": 1.0, "critical_failures": 0}
    assert events[0]["data"]["run"]["status"] == "completed"


async def test_heartbeat_comment_when_nothing_happens(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, producer: EventProducer
) -> None:
    run = await running_run(api, tenant, session_factory)
    stream = ProgressStream(
        BOOTSTRAP, session_factory, tenant.project_id, run.run_id, heartbeat_s=0.3
    )
    await stream.open()
    task = asyncio.create_task(collect(stream))
    await asyncio.sleep(1.5)
    await producer.publish(run_completed(run.run_id))
    chunks = await task
    assert chunks[0].startswith("id: ") and chunks[0].split("\n")[1] == "event: snapshot"
    heartbeats = [c for c in chunks if c == ": heartbeat\n\n"]
    assert len(heartbeats) >= 2
    assert chunks[-1].split("\n")[1] == "event: run.completed"


async def test_events_that_do_not_fit_the_sse_schema_are_skipped(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, producer: EventProducer
) -> None:
    run = await running_run(api, tenant, session_factory)
    stream = ProgressStream(BOOTSTRAP, session_factory, tenant.project_id, run.run_id)
    await stream.open()
    task = asyncio.create_task(collect(stream))
    await producer.publish(item_status(run.run_id, run.item_ids[1], "not-a-status"))
    await producer.publish(
        _event(
            run.run_id, kind="call.evaluated", call_id=uuid.uuid4(), overall_score=50, passed=True
        )  # a call that is in no run item: nothing to show
    )
    await producer.publish(item_status(run.run_id, run.item_ids[1], "evaluating"))
    await producer.publish(run_completed(run.run_id))
    names = [e["event"] for e in parse_sse(await task)]
    assert names == ["snapshot", "item.status", "run.completed"]


# ---------------------------------------------------------------------------------- HTTP


async def test_http_stream_headers_body_and_end_for_a_live_run(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, producer: EventProducer
) -> None:
    run = await running_run(api, tenant, session_factory)
    request = asyncio.create_task(
        api.get(f"{API}/runs/{run.run_id}/events", headers=tenant.read, timeout=60)
    )
    for _ in range(80):  # publish until the stream (opened after its snapshot) has seen them
        if request.done():
            break
        await producer.publish(item_status(run.run_id, run.item_ids[1], "in_progress"))
        await producer.publish(run_completed(run.run_id))
        await asyncio.sleep(0.5)
    response = await request
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    chunks = [c + "\n\n" for c in response.text.split("\n\n") if c]
    events = parse_sse(chunks)
    assert events[0]["event"] == "snapshot" and events[-1]["event"] == "run.completed"
    assert events[0]["data"]["run"]["id"] == str(run.run_id)


async def test_http_resume_uses_the_last_event_id_header(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, producer: EventProducer
) -> None:
    run = await running_run(api, tenant, session_factory)
    probe = ProgressStream(BOOTSTRAP, session_factory, tenant.project_id, run.run_id)
    await probe.open()
    stream_iter = probe.events()
    snapshot = parse_sse([await anext(stream_iter)])[0]
    await stream_iter.aclose()
    await producer.publish(item_status(run.run_id, run.item_ids[1], "in_progress"))
    await producer.publish(run_completed(run.run_id))
    response = await api.get(
        f"{API}/runs/{run.run_id}/events",
        headers={**tenant.read, "Last-Event-ID": snapshot["id"]},
        timeout=30,
    )
    names = [e["event"] for e in parse_sse([c + "\n\n" for c in response.text.split("\n\n") if c])]
    assert names == ["snapshot", "item.status", "run.completed"]


async def test_http_errors_before_the_stream_starts(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    other = await new_tenant(session_factory)
    theirs = await seed_run(api, session_factory, other, scores=[(80, True)])
    for run_id in (uuid.uuid4(), theirs.run_id):
        response = await api.get(f"{API}/runs/{run_id}/events", headers=tenant.read)
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
    mine = await seed_run(api, session_factory, tenant, scores=[(80, True)])
    assert (await api.get(f"{API}/runs/{mine.run_id}/events")).status_code == 401

    app.dependency_overrides[kafka_bootstrap] = lambda: "127.0.0.1:1"
    down = await api.get(f"{API}/runs/{mine.run_id}/events", headers=tenant.read)
    assert down.status_code == 502 and down.json()["error"]["code"] == "upstream_error"
    stream = ProgressStream("127.0.0.1:1", session_factory, tenant.project_id, mine.run_id)
    with pytest.raises(ApiError):
        await stream.open()


# ---------------------------------------------------------------------------------- cursor


def test_event_id_round_trips_and_rejects_foreign_values() -> None:
    assert encode_cursor({1: 7, 0: 41}) == "0:41,1:7"
    assert decode_cursor("0:41,1:7") == {0: 41, 1: 7}
    assert decode_cursor("0:-1") == {0: -1}
    for bad in (None, "", "garbage", "a:b", "0:41,", "0:1:2", "-1:5", "0:-2"):
        assert decode_cursor(bad) is None
