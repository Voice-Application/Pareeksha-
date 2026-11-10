"""A run item whose ``call.requested`` is given up on never stays active holding its slot.

Real Postgres, the real ``simulator`` handler (with a scripted call, as in
``test_simulator_worker.py``). A failure that escapes the handler after ``start_item`` used to
leave the item ``connecting`` / ``in_progress`` with ``test_runs.active_calls`` still counting it,
so the run never finished and its other items were throttled for ever.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient

from pareeksha.evaluation.completion_reconciler import reconcile_once
from pareeksha.evaluation.pg_stores import find_completable_runs
from pareeksha.events.consumer import ConsumerSpec, RetryPolicy, Throttled
from pareeksha.events.runtime import Database
from pareeksha.events.schemas import CallRequested, make_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.events.topics import MAX_ATTEMPTS, Topics
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.runs.slots import reconcile_slots
from pareeksha.simulation.store import give_up_item
from pareeksha.storage.blob import LocalBlobStore
from pareeksha.workers import simulator
from tests.conftest import Tenant
from tests.integration.audit_support import RUBRIC_SQL, fetch_rows, transaction
from tests.integration.harness import pipeline
from tests.integration.runs_support import API, make_fixture, plan_in_db, settings_for
from tests.integration.support import unique_group, wait_for
from tests.integration.test_simulator_worker import ScriptedRunner


class BrokenBlobs(LocalBlobStore):
    """A blob store whose upload fails after the call ran (outside ``_run_call``'s safety net)."""

    def __init__(self, root: Any, exc: Exception) -> None:
        super().__init__(root)
        self.exc = exc

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        raise self.exc


@pytest.fixture
async def install(database_url: str, tmp_path: Any) -> Any:
    settings = settings_for(database_url)
    db = Database(settings)
    usage = ApiUsageSink(settings)

    def _install(blobs: LocalBlobStore, runner: ScriptedRunner | None = None) -> None:
        simulator.configure(db=db, usage=usage, runner=runner or ScriptedRunner(), blobs=blobs)  # type: ignore[arg-type]

    yield _install
    simulator.configure()
    await db.close()
    await usage.close()


async def _requests(
    api: AsyncClient, tenant: Tenant, database_url: str, *, repeats: int = 3, cap: int = 3
) -> list[CallRequested]:
    fx = await make_fixture(api, tenant, 1, 1, 1)
    body = fx.body(repeats=repeats, config={"max_concurrency": cap})
    created = await api.post(f"{API}/runs", json=body, headers=tenant.admin)
    assert created.status_code == 201, created.text
    out = await plan_in_db(database_url, created.json()["id"])
    return [o.payload for o in out if isinstance(o.payload, CallRequested)]


async def _handle(req: CallRequested, database_url: str, *, attempt: int = 1) -> Any:
    env = make_envelope(req, producer="planner", correlation_id=str(req.run_id), attempt=attempt)
    async with transaction(database_url) as ctx:
        ctx.attempt = attempt
        return await simulator.on_call_requested(env, ctx)


async def _one(database_url: str, sql: str, *args: Any) -> dict[str, Any]:
    rows = await fetch_rows(database_url, sql, *args)
    assert len(rows) == 1, rows
    return rows[0]


async def _item(database_url: str, item_id: uuid.UUID) -> dict[str, Any]:
    return await _one(
        database_url, "SELECT status, last_error FROM run_items WHERE id = %s", item_id
    )


async def _active_calls(database_url: str, run_id: uuid.UUID) -> int:
    row = await _one(database_url, "SELECT active_calls FROM test_runs WHERE id = %s", run_id)
    return int(row["active_calls"])


async def test_a_permanent_failure_after_start_item_errors_the_item_and_frees_its_slot(
    api: AsyncClient, tenant: Tenant, database_url: str, install: Any, tmp_path: Any
) -> None:
    """Path (a): ``ValueError`` is permanent, so the framework sends the message to the DLQ."""
    install(BrokenBlobs(tmp_path, ValueError("bad blob key")))
    req = (await _requests(api, tenant, database_url))[0]

    with pytest.raises(ValueError):
        await _handle(req, database_url)

    item = await _item(database_url, req.run_item_id)
    assert item["status"] == "error"
    assert item["last_error"].startswith("infra: ValueError: bad blob key")
    call = await _one(
        database_url,
        "SELECT status, end_reason, error FROM calls WHERE run_item_id = %s",
        req.run_item_id,
    )
    assert call["status"] == "error" and call["end_reason"] == "infra_error"
    assert await _active_calls(database_url, req.run_id) == 0


async def test_a_retryable_failure_keeps_the_slot_until_the_last_attempt(
    api: AsyncClient, tenant: Tenant, database_url: str, install: Any, tmp_path: Any
) -> None:
    """Path (b): attempts 1..MAX-1 are retried (the item keeps its slot and resumes); the last
    attempt goes to the DLQ, so the item is given up on there."""
    install(BrokenBlobs(tmp_path, OSError("blob store unreachable")))
    req = (await _requests(api, tenant, database_url))[0]

    for attempt in range(1, MAX_ATTEMPTS):
        with pytest.raises(OSError):
            await _handle(req, database_url, attempt=attempt)
        assert (await _item(database_url, req.run_item_id))["status"] == "in_progress"
        assert await _active_calls(database_url, req.run_id) == 1

    with pytest.raises(OSError):
        await _handle(req, database_url, attempt=MAX_ATTEMPTS)

    item = await _item(database_url, req.run_item_id)
    assert item["status"] == "error" and "blob store unreachable" in item["last_error"]
    assert await _active_calls(database_url, req.run_id) == 0
    # the slot-counter reconciler agrees: nothing left to repair
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        assert [r for r in await reconcile_slots(c) if r.run_id == req.run_id] == []


async def test_a_run_with_a_given_up_item_frees_the_cap_and_completes(
    api: AsyncClient, tenant: Tenant, database_url: str, install: Any, tmp_path: Any
) -> None:
    """Cap 1: the failed item's slot goes to the next ones, and the run then finishes ``partial``
    with the failure counted as an error, outside the pass rate (not as a failed call)."""
    reqs = await _requests(api, tenant, database_url, cap=1)
    install(BrokenBlobs(tmp_path, ValueError("bad blob key")))
    with pytest.raises(ValueError):
        await _handle(reqs[0], database_url)

    install(LocalBlobStore(tmp_path / "ok"))
    calls = []
    for req in reqs[1:]:
        out = await _handle(req, database_url)  # not Throttled: the slot was given back
        calls.append(out[0].payload.call_id)
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        assert reqs[0].run_id not in await find_completable_runs(c)  # two calls to judge
        # stand-in for the evaluator: one call passed, one failed
        cur = await c.execute(RUBRIC_SQL + " RETURNING id", (f"stuck-{uuid.uuid4()}",))
        rubric = await cur.fetchone()
        assert rubric is not None
        rubric_id = rubric[0]
        for call_id, score, passed in zip(calls, (80, 40), (True, False), strict=True):
            await c.execute(
                "INSERT INTO evaluations (call_id, rubric_version_id, judge_model, prompt_hash, "
                "overall_score, passed) VALUES (%s, %s, 'test', 'h', %s, %s)",
                (call_id, rubric_id, score, passed),
            )
        await c.execute(
            "UPDATE run_items SET status = 'evaluated' WHERE id = ANY(%s)",
            ([r.run_item_id for r in reqs[1:]],),
        )
        done = await reconcile_once(c)
    assert reqs[0].run_id in done
    run = await _one(
        database_url,
        "SELECT status, summary, active_calls FROM test_runs WHERE id = %s",
        reqs[0].run_id,
    )
    assert run["status"] == "partial" and run["active_calls"] == 0
    summary = run["summary"]
    assert summary["item_count"] == 3 and summary["error_count"] == 1
    assert summary["evaluated_count"] == 2 and summary["pass_rate"] == 0.5
    assert summary["score_mean"] == 60


async def test_a_run_whose_only_item_was_given_up_finishes_failed_without_a_pass_rate(
    api: AsyncClient, tenant: Tenant, database_url: str, install: Any, tmp_path: Any
) -> None:
    req = (await _requests(api, tenant, database_url, repeats=1))[0]
    install(BrokenBlobs(tmp_path, ValueError("bad blob key")))
    with pytest.raises(ValueError):
        await _handle(req, database_url)
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        assert req.run_id in await reconcile_once(c)
    run = await _one(
        database_url, "SELECT status, summary FROM test_runs WHERE id = %s", req.run_id
    )
    assert run["status"] == "failed"
    assert run["summary"]["error_count"] == 1 and run["summary"]["pass_rate"] is None


class GivenUpMidCall(ScriptedRunner):
    """The reconciler gives the item up while its call is still running."""

    def __init__(self, database_url: str, run_item_id: uuid.UUID) -> None:
        super().__init__()
        self.url = libpq_url(database_url)
        self.run_item_id = run_item_id

    async def run(self, spec: Any) -> Any:
        async with await psycopg.AsyncConnection.connect(self.url, autocommit=True) as c:
            assert await give_up_item(c, self.run_item_id, "infra: stale") == "error"
        return await super().run(spec)


async def test_a_worker_finishing_after_its_item_was_given_up_discards_its_result(
    api: AsyncClient, tenant: Tenant, database_url: str, install: Any, tmp_path: Any
) -> None:
    reqs = await _requests(api, tenant, database_url, repeats=2, cap=2)
    req, other = reqs
    # another item holds the run's other slot: a second release would show up as 0
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        await c.execute(
            "UPDATE run_items SET status = 'in_progress' WHERE id = %s", (other.run_item_id,)
        )
        await c.execute("UPDATE test_runs SET active_calls = 1 WHERE id = %s", (req.run_id,))
    install(LocalBlobStore(tmp_path), GivenUpMidCall(database_url, req.run_item_id))

    assert await _handle(req, database_url) == []  # no error, no retry, no call.completed

    assert await _item(database_url, req.run_item_id) == {
        "status": "error",
        "last_error": "infra: stale",
    }
    call = await _one(
        database_url,
        "SELECT status, end_reason, duration_ms FROM calls WHERE run_item_id = %s",
        req.run_item_id,
    )
    assert call == {"status": "error", "end_reason": "infra_error", "duration_ms": None}
    turns = await fetch_rows(
        database_url,
        "SELECT 1 FROM turns WHERE call_id = (SELECT id FROM calls WHERE run_item_id = %s)",
        req.run_item_id,
    )
    assert turns == []
    assert await _active_calls(database_url, req.run_id) == 1


async def test_on_kafka_a_call_that_keeps_failing_ends_in_the_dlq_with_its_item_given_up(
    api: AsyncClient, tenant: Tenant, database_url: str, install: Any, tmp_path: Any
) -> None:
    """The real consumer framework, retrier and DLQ recorder: three attempts, each resuming
    the item in its slot, then the DLQ; the item is ``error`` and its slot is free."""
    runner = ScriptedRunner()
    install(BrokenBlobs(tmp_path, OSError("blob store unreachable")), runner)
    req = (await _requests(api, tenant, database_url))[0]
    spec = ConsumerSpec(
        group=unique_group("sim"),
        topics=(Topics.CALL_REQUESTED,),
        handler=simulator.on_call_requested,
        reproduce=simulator._reproduce,
    )
    policy = RetryPolicy(delay_seconds={2: 0.2, 3: 0.2})
    async with pipeline(spec, policy=policy, settings=settings_for(database_url)) as pl:
        await pl.send(make_envelope(req, producer="planner", correlation_id=str(req.run_id)))

        async def recorded() -> bool:
            rows = await fetch_rows(
                database_url,
                "SELECT 1 FROM dead_letters WHERE consumer_group = %s AND status = 'open'",
                spec.group,
            )
            return len(rows) == 1

        await wait_for(recorded, timeout=60, what="the call.requested dead letter")

    assert len(runner.specs) == MAX_ATTEMPTS
    item = await _item(database_url, req.run_item_id)
    assert item["status"] == "error" and "blob store unreachable" in item["last_error"]
    assert await _active_calls(database_url, req.run_id) == 0
    dead = await _one(
        database_url,
        "SELECT envelope->'payload'->>'run_item_id' AS item, attempts FROM dead_letters "
        "WHERE consumer_group = %s",
        spec.group,
    )
    assert dead == {"item": str(req.run_item_id), "attempts": MAX_ATTEMPTS}
    # what the reconciler's dead-letter pass would do next is a no-op for this item
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        statuses = frozenset({"queued", "connecting", "in_progress"})
        assert await give_up_item(c, req.run_item_id, "again", statuses=statuses) is None


async def test_without_the_fix_the_next_item_would_be_throttled(
    api: AsyncClient, tenant: Tenant, database_url: str, install: Any, tmp_path: Any
) -> None:
    """Control for the test above: while an item really holds the only slot, others wait."""
    reqs = await _requests(api, tenant, database_url, repeats=2, cap=1)
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        await c.execute(
            "UPDATE run_items SET status = 'in_progress' WHERE id = %s", (reqs[0].run_item_id,)
        )
        await c.execute("UPDATE test_runs SET active_calls = 1 WHERE id = %s", (reqs[0].run_id,))
    install(LocalBlobStore(tmp_path))
    with pytest.raises(Throttled):
        await _handle(reqs[1], database_url)
