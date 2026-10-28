"""The ``simulator`` handler against real Postgres: slots, saving, duplicates, failures (VOICE-05).

The call itself is scripted (``ScriptedRunner``): the pipeline has its own suite, and the real
Gnani/DeepSeek/Kafka end-to-end run is in ``proof/VOICE-05``.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient

from pareeksha.events.consumer import Throttled
from pareeksha.events.runtime import Database
from pareeksha.events.schemas import CallCompleted, CallRequested, make_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.events.topics import Topics
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.simulation.models import CallResult, CallSpec, ToolCallRecord, TurnRecord
from pareeksha.simulation.recorder import Recordings
from pareeksha.simulation.runner import CallOutcome
from pareeksha.storage.blob import LocalBlobStore
from pareeksha.workers import simulator
from tests.conftest import Tenant
from tests.integration.audit_support import fetch_rows, transaction
from tests.integration.runs_support import API, make_fixture, plan_in_db, settings_for


def _wav(seconds: float = 0.2) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


class ScriptedRunner:
    """Stands in for ``CallRunner``: returns a canned call (or raises) and records the specs."""

    def __init__(self, end_reason: str = "agent_hangup", *, boom: bool = False) -> None:
        self.end_reason = end_reason
        self.boom = boom
        self.specs: list[CallSpec] = []

    async def run(self, spec: CallSpec) -> CallOutcome:
        self.specs.append(spec)
        if self.boom:
            raise RuntimeError("pipeline exploded")
        failed = self.end_reason in ("infra_error", "connect_failed")
        result = CallResult(
            call_id=spec.call_id,
            end_reason=self.end_reason,  # type: ignore[arg-type]
            duration_ms=4200,
            turns=[
                TurnRecord(
                    idx=0, speaker="agent", text="hello recorded call", start_ms=0, end_ms=1500
                ),
                TurnRecord(
                    idx=1,
                    speaker="caller",
                    text="my number is 9876543210",
                    start_ms=2000,
                    end_ms=3500,
                    is_barge_in=True,
                ),
            ],
            tool_calls=[
                ToolCallRecord(seq=0, name="record_promise_to_pay", arguments={"a": 1}, at_ms=3600)
            ],
            error="no route to agent" if failed else None,
        )
        wav = _wav()
        return CallOutcome(result, None if failed else Recordings(wav, wav, wav, 200))


@pytest.fixture
async def worker(database_url: str, tmp_path: Any) -> Any:
    settings = settings_for(database_url)
    db = Database(settings)
    usage = ApiUsageSink(settings)
    blobs = LocalBlobStore(tmp_path)

    def install(runner: ScriptedRunner) -> None:
        simulator.configure(db=db, usage=usage, runner=runner, blobs=blobs)  # type: ignore[arg-type]

    yield install, blobs
    simulator.configure()
    await db.close()
    await usage.close()


async def _requests(
    api: AsyncClient, tenant: Tenant, database_url: str, *, max_concurrency: int = 3
) -> list[CallRequested]:
    fx = await make_fixture(api, tenant, 1, 1, 1)
    body = fx.body(repeats=3, config={"max_concurrency": max_concurrency})
    created = await api.post(f"{API}/runs", json=body, headers=tenant.admin)
    assert created.status_code == 201, created.text
    out = await plan_in_db(database_url, created.json()["id"])
    return [o.payload for o in out if isinstance(o.payload, CallRequested)]


async def _handle(req: CallRequested, database_url: str) -> Any:
    env = make_envelope(req, producer="planner", correlation_id=str(req.run_id))
    async with transaction(database_url) as ctx:
        return await simulator.on_call_requested(env, ctx)


async def _one(database_url: str, sql: str, *args: Any) -> dict[str, Any]:
    rows = await fetch_rows(database_url, sql, *args)
    assert len(rows) == 1, rows
    return rows[0]


async def test_a_call_is_saved_the_slot_released_and_call_completed_produced(
    api: AsyncClient, tenant: Tenant, database_url: str, worker: Any
) -> None:
    install, blobs = worker
    runner = ScriptedRunner()
    install(runner)
    req = (await _requests(api, tenant, database_url))[0]

    out = await _handle(req, database_url)

    assert [type(o.payload) for o in out] == [CallCompleted]
    done = out[0].payload
    assert done.source == "simulation" and done.run_item_id == req.run_item_id
    assert done.run_id == req.run_id and done.end_reason == "agent_hangup"
    spec = runner.specs[0]
    assert spec.call_id == done.call_id and spec.persona.language == "kn-IN"
    assert spec.profile.sample_rate == 8000 and spec.profile.background == "market_crowd"

    call = await _one(database_url, "SELECT * FROM calls WHERE id = %s", done.call_id)
    assert call["status"] == "completed" and call["source"] == "simulation"
    assert call["run_item_id"] == req.run_item_id and call["duration_ms"] == 4200
    assert await blobs.exists(call["recording_mixed"]) and await blobs.exists(
        call["recording_agent"]
    )
    turns = await fetch_rows(
        database_url, "SELECT * FROM turns WHERE call_id = %s ORDER BY idx", done.call_id
    )
    assert [t["speaker"] for t in turns] == ["agent", "caller"]
    assert "9876543210" in turns[1]["text"] and "9876543210" not in turns[1]["text_masked"]
    assert turns[1]["is_barge_in"] is True
    tools = await fetch_rows(
        database_url, "SELECT * FROM tool_calls WHERE call_id = %s", done.call_id
    )
    assert [t["name"] for t in tools] == ["record_promise_to_pay"]
    item = await _one(database_url, "SELECT status FROM run_items WHERE id = %s", req.run_item_id)
    assert item["status"] == "completed"
    run = await _one(
        database_url, "SELECT active_calls, status FROM test_runs WHERE id = %s", req.run_id
    )
    assert run["active_calls"] == 0 and run["status"] == "running"


async def test_at_the_cap_the_message_is_throttled_and_nothing_runs(
    api: AsyncClient, tenant: Tenant, database_url: str, worker: Any
) -> None:
    install, _ = worker
    runner = ScriptedRunner()
    install(runner)
    reqs = await _requests(api, tenant, database_url, max_concurrency=1)
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        await c.execute(
            "UPDATE run_items SET status = 'in_progress' WHERE id = %s", (reqs[0].run_item_id,)
        )
        await c.execute("UPDATE test_runs SET active_calls = 1 WHERE id = %s", (reqs[0].run_id,))

    with pytest.raises(Throttled):
        await _handle(reqs[1], database_url)

    assert runner.specs == []
    item = await _one(
        database_url, "SELECT status FROM run_items WHERE id = %s", reqs[1].run_item_id
    )
    assert item["status"] == "queued"


async def test_a_cancelled_item_is_skipped(
    api: AsyncClient, tenant: Tenant, database_url: str, worker: Any
) -> None:
    install, _ = worker
    runner = ScriptedRunner()
    install(runner)
    req = (await _requests(api, tenant, database_url))[0]
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        await c.execute(
            "UPDATE run_items SET status = 'cancelled' WHERE id = %s", (req.run_item_id,)
        )

    assert await _handle(req, database_url) == []
    assert runner.specs == []


async def test_a_failed_call_errors_the_item_frees_the_slot_and_skips_the_evaluator(
    api: AsyncClient, tenant: Tenant, database_url: str, worker: Any
) -> None:
    install, _ = worker
    install(ScriptedRunner("connect_failed"))
    req = (await _requests(api, tenant, database_url))[0]

    assert await _handle(req, database_url) == []

    call = await _one(
        database_url,
        "SELECT status, end_reason, error FROM calls WHERE run_item_id = %s",
        req.run_item_id,
    )
    assert call == {"status": "error", "end_reason": "connect_failed", "error": "no route to agent"}
    item = await _one(
        database_url, "SELECT status, last_error FROM run_items WHERE id = %s", req.run_item_id
    )
    assert item["status"] == "error" and item["last_error"] == "no route to agent"
    run = await _one(database_url, "SELECT active_calls FROM test_runs WHERE id = %s", req.run_id)
    assert run["active_calls"] == 0


async def test_a_crashing_pipeline_becomes_an_infra_error_call(
    api: AsyncClient, tenant: Tenant, database_url: str, worker: Any
) -> None:
    install, _ = worker
    install(ScriptedRunner(boom=True))
    req = (await _requests(api, tenant, database_url))[0]

    assert await _handle(req, database_url) == []

    call = await _one(
        database_url,
        "SELECT status, end_reason, error FROM calls WHERE run_item_id = %s",
        req.run_item_id,
    )
    assert call["status"] == "error" and call["end_reason"] == "infra_error"
    assert "pipeline exploded" in call["error"]


async def test_a_redelivery_resumes_the_slot_and_a_duplicate_reproduces_the_event(
    api: AsyncClient, tenant: Tenant, database_url: str, worker: Any
) -> None:
    install, _ = worker
    runner = ScriptedRunner()
    install(runner)
    req = (await _requests(api, tenant, database_url))[0]
    # a crash after start_item left the item holding its slot
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        await c.execute(
            "UPDATE run_items SET status = 'connecting' WHERE id = %s", (req.run_item_id,)
        )
        await c.execute("UPDATE test_runs SET active_calls = 1 WHERE id = %s", (req.run_id,))

    first = await _handle(req, database_url)
    run = await _one(database_url, "SELECT active_calls FROM test_runs WHERE id = %s", req.run_id)
    assert run["active_calls"] == 0 and len(runner.specs) == 1

    env = make_envelope(req, producer="planner", correlation_id=str(req.run_id))
    async with transaction(database_url) as ctx:
        again = await simulator._reproduce(
            env,  # type: ignore[arg-type]
            dataclasses.replace(ctx, duplicate=True),
        )
    assert [o.payload for o in again] == [o.payload for o in first]
    assert len(runner.specs) == 1
    assert Topics.CALL_COMPLETED.value == first[0].payload.topic.value
    assert uuid.UUID(str(first[0].payload.call_id)) == runner.specs[0].call_id
