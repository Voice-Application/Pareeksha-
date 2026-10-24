"""POST /runs, /runs:estimate, GET /runs, /runs/{id}, /items, cancel (API-03, FR-RN-1, FR-RN-2).

Real app, real Alembic-migrated Postgres. The planner step that creates the items is run through
the planner's own handler (``plan_in_db``); the Kafka path is in ``test_planner.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.errors import ApiError
from pareeksha.db import models
from pareeksha.runs import service
from tests.conftest import Tenant, bearer, make_api_key
from tests.integration.runs_support import API, Fixture, make_fixture, plan_in_db

Factory = async_sessionmaker[AsyncSession]


async def _create(api: AsyncClient, tenant: Tenant, fx: Fixture, **overrides: Any) -> str:
    response = await api.post(f"{API}/runs", json=fx.body(**overrides), headers=tenant.admin)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _outbox(factory: Factory, run_id: str, topic: str | None = None) -> list[Any]:
    async with factory() as session:
        stmt = select(models.OutboxEvents).where(models.OutboxEvents.key == run_id)
        if topic:
            stmt = stmt.where(models.OutboxEvents.topic == topic)
        return list((await session.scalars(stmt.order_by(models.OutboxEvents.created_at))).all())


# ---------------------------------------------------------------------------------- create


async def test_create_run_writes_run_and_run_requested_outbox_row(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    fx = await make_fixture(api, tenant, scenarios=2, personas=2, profiles=2)
    response = await api.post(
        f"{API}/runs",
        json=fx.body(repeats=2, config={"max_concurrency": 4, "seed": 7}),
        headers=tenant.admin,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued" and body["item_count"] == 2 * 2 * 2 * 2
    assert set(body["estimate"]) == {
        "tts_seconds",
        "stt_seconds",
        "judge_calls",
        "caller_llm_calls",
        "est_cost",
    }
    assert body["estimate"]["judge_calls"] == 16

    run_id = body["id"]
    async with session_factory() as session:
        run = await session.get(models.TestRuns, uuid.UUID(run_id))
    assert run is not None
    assert run.project_id == tenant.project_id and run.status == "queued"
    assert run.active_calls == 0 and run.kind == "matrix" and run.name == "baseline"
    assert run.config["max_concurrency"] == 4 and run.config["seed"] == 7  # type: ignore[index]
    assert run.config["item_count"] == 16  # type: ignore[index]
    assert run.agent_snapshot["name"].startswith("EMI bot")  # type: ignore[index]
    assert "adapter_secrets_encrypted" not in run.agent_snapshot  # type: ignore[operator]

    (row,) = await _outbox(session_factory, run_id)
    assert row.topic == "pareeksha.run.requested.v1" and row.published_at is None
    envelope = row.envelope
    assert envelope["type"] == "run.requested" and envelope["producer"] == "api"
    assert envelope["correlation_id"] == run_id and row.id == uuid.UUID(envelope["event_id"])
    payload = envelope["payload"]
    assert payload["run_id"] == run_id and payload["agent_id"] == fx.agent_id
    assert payload["kind"] == "matrix" and payload["repeats"] == 2 and payload["seed"] == 7
    assert payload["scenario_ids"] == fx.scenario_ids
    assert payload["persona_ids"] == fx.persona_ids
    assert payload["noise_profile_ids"] == fx.noise_profile_ids
    # the planner (not the API) creates the items
    async with session_factory() as session:
        items = await session.scalar(
            select(func.count())
            .select_from(models.RunItems)
            .where(models.RunItems.run_id == uuid.UUID(run_id))
        )
        assert items == 0


async def test_run_and_outbox_row_commit_or_roll_back_together(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fx = await make_fixture(api, tenant, 1, 1, 1)

    def broken_enqueue(*_: Any) -> None:
        raise ApiError(500, "internal_error", "outbox unavailable")

    monkeypatch.setattr(service, "enqueue_session", broken_enqueue)
    response = await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)
    assert response.status_code == 500
    async with session_factory() as session:
        runs = await session.scalar(
            select(func.count())
            .select_from(models.TestRuns)
            .where(models.TestRuns.project_id == tenant.project_id)
        )
    assert runs == 0  # the run row was flushed first, then rolled back with the failed outbox


async def test_create_validates_references_and_is_project_scoped(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, session_factory: Factory
) -> None:
    fx = await make_fixture(api, tenant, 1, 1, 1)
    foreign = await make_fixture(api, other_tenant, 1, 1, 1)
    missing = str(uuid.uuid4())
    cases = {
        "agent": fx.body(agent_id=missing),
        "foreign agent": fx.body(agent_id=foreign.agent_id),
        "scenario": fx.body(scenario_ids=[missing]),
        "foreign scenario": fx.body(scenario_ids=foreign.scenario_ids),
        "persona": fx.body(persona_ids=[missing]),
        "noise profile": fx.body(noise_profile_ids=[missing]),
    }
    for name, body in cases.items():
        response = await api.post(f"{API}/runs", json=body, headers=tenant.admin)
        assert response.status_code == 404, name
        assert response.json()["error"]["code"] == "not_found", name
    # empty lists and a bad repeat count are validation errors (400, not 422)
    for body in (fx.body(scenario_ids=[]), fx.body(repeats=0), fx.body(kind="regression")):
        response = await api.post(f"{API}/runs", json=body, headers=tenant.admin)
        assert response.status_code == 400
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(models.TestRuns)
                .where(models.TestRuns.project_id == tenant.project_id)
            )
            == 0
        )


async def test_archived_agent_cannot_start_a_run(api: AsyncClient, tenant: Tenant) -> None:
    fx = await make_fixture(api, tenant, 1, 1, 1)
    archived = await api.post(f"{API}/agents/{fx.agent_id}/archive", headers=tenant.admin)
    assert archived.status_code == 200, archived.text
    response = await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)
    assert response.status_code == 409


async def test_duplicate_ids_are_collapsed_and_oversized_matrices_refused(
    api: AsyncClient, tenant: Tenant
) -> None:
    fx = await make_fixture(api, tenant, 2, 1, 1)
    doubled = fx.body(scenario_ids=fx.scenario_ids + fx.scenario_ids)
    estimate = await api.post(f"{API}/runs:estimate", json=doubled, headers=tenant.read)
    assert estimate.json()["item_count"] == 2
    big = await make_fixture(api, tenant, 11, 10, 10)  # 1100 > 1000 items
    response = await api.post(f"{API}/runs", json=big.body(), headers=tenant.admin)
    assert response.status_code == 400
    assert response.json()["error"]["details"] == {"item_count": 1100, "max_items": 1000}


async def test_scopes_read_key_cannot_create_but_can_estimate(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    fx = await make_fixture(api, tenant, 1, 1, 1)
    denied = await api.post(f"{API}/runs", json=fx.body(), headers=tenant.read)
    assert denied.status_code == 403
    allowed = await api.post(f"{API}/runs:estimate", json=fx.body(), headers=tenant.read)
    assert allowed.status_code == 200
    writer = bearer(await make_api_key(session_factory, tenant.project_id, ["runs:write"]))
    assert (await api.post(f"{API}/runs", json=fx.body(), headers=writer)).status_code == 201
    anonymous = await api.post(f"{API}/runs", json=fx.body())
    assert anonymous.status_code == 401


# ------------------------------------------------------------------- estimate and budget


async def test_estimate_creates_nothing_and_matches_create(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COST_STT_STREAM_PER_MIN", "2")
    monkeypatch.setenv("COST_TTS_PER_1K_CHARS", "1")
    monkeypatch.setenv("BUDGET_CREDITS", "1000")
    fx = await make_fixture(api, tenant, 2, 2, 1, max_turns=10)
    estimate = (await api.post(f"{API}/runs:estimate", json=fx.body(), headers=tenant.read)).json()
    assert estimate["item_count"] == 4 and estimate["over_budget"] is False
    assert estimate["remaining_budget"] == 1000
    assert (await _count_runs(session_factory, tenant)) == 0
    created = (await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)).json()
    assert created["estimate"] == estimate["estimate"] and created["estimate"]["est_cost"] > 0
    # 4 calls x 10 turns x 6 s = 240 s of STT, half of it spoken by the caller (TTS)
    assert created["estimate"]["stt_seconds"] == 240 and created["estimate"]["tts_seconds"] == 120
    assert created["estimate"]["caller_llm_calls"] == 20 and created["estimate"]["judge_calls"] == 4


async def _count_runs(factory: Factory, tenant: Tenant) -> int:
    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(models.TestRuns)
            .where(models.TestRuns.project_id == tenant.project_id)
        )
    return int(count or 0)


async def test_over_budget_run_gets_402_with_the_estimate_unless_confirmed(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COST_STT_STREAM_PER_MIN", "10")
    monkeypatch.setenv("BUDGET_CREDITS", "5")
    fx = await make_fixture(api, tenant, 2, 2, 2, max_turns=10)
    estimate = (await api.post(f"{API}/runs:estimate", json=fx.body(), headers=tenant.read)).json()
    assert estimate["over_budget"] is True and estimate["estimate"]["est_cost"] > 5

    refused = await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)
    assert refused.status_code == 402
    error = refused.json()["error"]
    assert error["code"] == "budget_exceeded"
    assert error["details"]["estimate"] == estimate["estimate"]
    assert error["details"]["remaining_budget"] == 5
    assert await _count_runs(session_factory, tenant) == 0  # nothing was written

    forced = await api.post(
        f"{API}/runs", json=fx.body(confirm_over_budget=True), headers=tenant.admin
    )
    assert forced.status_code == 201
    assert await _count_runs(session_factory, tenant) == 1


async def test_remaining_budget_subtracts_api_usage(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUDGET_CREDITS", "100")
    async with session_factory() as session:
        session.add(
            models.ApiUsage(provider="gnani", operation="tts", units=1, unit_type="characters")
        )
        session.add(
            models.ApiUsage(
                provider="gnani", operation="tts", units=1, unit_type="characters", est_cost=40.5
            )
        )
        await session.commit()
        before = await session.scalar(select(func.coalesce(func.sum(models.ApiUsage.est_cost), 0)))
    fx = await make_fixture(api, tenant, 1, 1, 1)
    estimate = (await api.post(f"{API}/runs:estimate", json=fx.body(), headers=tenant.read)).json()
    assert estimate["remaining_budget"] == pytest.approx(100 - float(before or 0), abs=0.01)
    monkeypatch.delenv("BUDGET_CREDITS")
    estimate = (await api.post(f"{API}/runs:estimate", json=fx.body(), headers=tenant.read)).json()
    assert estimate["remaining_budget"] is None and estimate["over_budget"] is False


async def test_dry_run_estimate_has_no_speech(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COST_STT_STREAM_PER_MIN", "10")
    fx = await make_fixture(api, tenant, 1, 1, 1)
    estimate = (
        await api.post(f"{API}/runs:estimate", json=fx.body(kind="dry_run"), headers=tenant.read)
    ).json()
    assert estimate["estimate"]["stt_seconds"] == 0 and estimate["estimate"]["tts_seconds"] == 0
    assert estimate["estimate"]["est_cost"] == 0 and estimate["estimate"]["caller_llm_calls"] > 0


# ---------------------------------------------------------------------------------- read


async def test_get_run_before_and_after_planning_and_progress_buckets(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, database_url: str
) -> None:
    fx = await make_fixture(api, tenant, 2, 2, 1)
    run_id = await _create(api, tenant, fx)
    url = f"{API}/runs/{run_id}"
    run = (await api.get(url, headers=tenant.read)).json()
    assert run["status"] == "queued" and run["kind"] == "matrix" and run["agent_id"] == fx.agent_id
    assert run["progress"] == {
        "total": 4,
        "queued": 4,
        "in_progress": 0,
        "evaluated": 0,
        "error": 0,
    }
    assert run["summary"]["pass_rate"] is None and run["started_at"] is None
    assert run["estimated_cost"] is not None

    await plan_in_db(database_url, run_id)
    async with session_factory() as session:
        ids = list(
            (
                await session.scalars(
                    select(models.RunItems.id)
                    .where(models.RunItems.run_id == uuid.UUID(run_id))
                    .order_by(models.RunItems.id)
                )
            ).all()
        )
        for item_id, status in zip(ids, ["in_progress", "evaluated", "judge_error", "queued"]):
            await session.execute(
                update(models.RunItems).where(models.RunItems.id == item_id).values(status=status)
            )
        await session.execute(
            update(models.TestRuns)
            .where(models.TestRuns.id == uuid.UUID(run_id))
            .values(summary={"pass_rate": 0.5, "top_failure_types": [["asr_misrecognition", 2]]})
        )
        await session.commit()
    run = (await api.get(url, headers=tenant.read)).json()
    assert run["progress"] == {
        "total": 4,
        "queued": 1,
        "in_progress": 1,
        "evaluated": 1,
        "error": 1,
    }
    assert run["summary"]["pass_rate"] == 0.5
    assert run["summary"]["top_failure_types"] == [["asr_misrecognition", 2]]


async def test_run_reads_are_project_scoped(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    fx = await make_fixture(api, tenant, 1, 1, 1)
    run_id = await _create(api, tenant, fx)
    for path in (f"/runs/{run_id}", f"/runs/{run_id}/items"):
        assert (await api.get(f"{API}{path}", headers=other_tenant.read)).status_code == 404
    cancel = await api.post(f"{API}/runs/{run_id}/cancel", headers=other_tenant.admin)
    assert cancel.status_code == 404
    other_list = (await api.get(f"{API}/runs", headers=other_tenant.read)).json()
    assert other_list["items"] == []
    assert (await api.get(f"{API}/runs/{uuid.uuid4()}", headers=tenant.read)).status_code == 404


async def test_list_runs_filters_and_pages(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    fx = await make_fixture(api, tenant, 1, 1, 1)
    fx2 = await make_fixture(api, tenant, 1, 1, 1)
    ids = [await _create(api, tenant, fx, name=f"r{i}") for i in range(3)]
    dry = await _create(api, tenant, fx2, kind="dry_run")
    cancelled = (await api.post(f"{API}/runs/{ids[0]}/cancel", headers=tenant.admin)).status_code
    assert cancelled == 202

    everything = (await api.get(f"{API}/runs", headers=tenant.read)).json()
    assert [r["id"] for r in everything["items"]] == [dry, ids[2], ids[1], ids[0]]  # newest first
    by_agent = (await api.get(f"{API}/runs?agent_id={fx.agent_id}", headers=tenant.read)).json()
    assert {r["id"] for r in by_agent["items"]} == set(ids)
    by_kind = (await api.get(f"{API}/runs?kind=dry_run", headers=tenant.read)).json()
    assert [r["id"] for r in by_kind["items"]] == [dry]
    by_status = (await api.get(f"{API}/runs?status=cancelled", headers=tenant.read)).json()
    assert [r["id"] for r in by_status["items"]] == [ids[0]]
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert (
        await api.get(f"{API}/runs", params={"created_from": future}, headers=tenant.read)
    ).json()["items"] == []
    in_window = await api.get(
        f"{API}/runs", params={"created_from": past, "created_to": future}, headers=tenant.read
    )
    assert len(in_window.json()["items"]) == 4

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(4):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await api.get(f"{API}/runs", params=params, headers=tenant.read)).json()
        seen += [r["id"] for r in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [dry, ids[2], ids[1], ids[0]]
    bad = await api.get(f"{API}/runs", params={"cursor": "nope"}, headers=tenant.read)
    assert bad.status_code == 400


async def test_items_listing_joins_names_call_and_latest_evaluation(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, database_url: str
) -> None:
    fx = await make_fixture(api, tenant, 2, 1, 1)
    run_id = await _create(api, tenant, fx)
    await plan_in_db(database_url, run_id)
    first = (await api.get(f"{API}/runs/{run_id}/items?limit=1", headers=tenant.read)).json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    rest = (
        await api.get(
            f"{API}/runs/{run_id}/items",
            params={"cursor": first["next_cursor"]},
            headers=tenant.read,
        )
    ).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None
    items = first["items"] + rest["items"]
    assert {i["scenario"][:10] for i in items} == {"Scenario 0", "Scenario 1"}
    assert all(i["persona"].startswith("Persona 0") for i in items)
    assert all(i["noise_profile"].startswith("profile_0_") for i in items)
    assert all(i["status"] == "queued" and i["call_id"] is None for i in items)

    target = uuid.UUID(items[0]["id"])
    async with session_factory() as session:
        rubrics = [
            models.RubricVersions(
                version=f"test-{uuid.uuid4().hex[:6]}", dimensions=[], prompt_hash="h"
            )
            for _ in range(2)
        ]
        call = models.Calls(
            project_id=tenant.project_id,
            agent_id=uuid.UUID(fx.agent_id),
            run_item_id=target,
            source="simulation",
            status="completed",
        )
        session.add_all([*rubrics, call])
        await session.flush()
        call_id = call.id
        # two evaluations of one call (two rubric versions): the most recent is reported
        for rubric, score, passed, critical, age in (
            (rubrics[0], 40, False, True, timedelta(hours=1)),
            (rubrics[1], 86.5, True, False, timedelta(0)),
        ):
            session.add(
                models.Evaluations(
                    call_id=call_id,
                    rubric_version_id=rubric.id,
                    judge_model="m",
                    prompt_hash="h",
                    overall_score=score,
                    passed=passed,
                    critical_failure=critical,
                    created_at=datetime.now(UTC) - age,
                )
            )
        await session.commit()
    again = (await api.get(f"{API}/runs/{run_id}/items", headers=tenant.read)).json()["items"]
    judged = next(i for i in again if i["id"] == str(target))
    assert judged["call_id"] == str(call_id)
    assert judged["overall_score"] == 86.5 and judged["passed"] is True
    assert judged["critical_failure"] is False
    other = next(i for i in again if i["id"] != str(target))
    assert other["call_id"] is None and other["overall_score"] is None and other["passed"] is None


# ---------------------------------------------------------------------------------- cancel


async def test_cancel_cancels_queued_items_and_tells_the_live_view(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, database_url: str
) -> None:
    fx = await make_fixture(api, tenant, 2, 2, 1)
    run_id = await _create(api, tenant, fx)
    await plan_in_db(database_url, run_id)
    async with session_factory() as session:
        busy = await session.scalar(
            select(models.RunItems.id)
            .where(models.RunItems.run_id == uuid.UUID(run_id))
            .order_by(models.RunItems.id)
            .limit(1)
        )
        await session.execute(
            update(models.RunItems).where(models.RunItems.id == busy).values(status="in_progress")
        )
        await session.commit()

    response = await api.post(f"{API}/runs/{run_id}/cancel", headers=tenant.admin)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "cancelled" and body["finished_at"] is not None
    assert body["progress"]["in_progress"] == 1  # an in-flight call is left to finish
    items = (await api.get(f"{API}/runs/{run_id}/items", headers=tenant.read)).json()["items"]
    assert sorted(i["status"] for i in items) == ["cancelled"] * 3 + ["in_progress"]

    progress = await _outbox(session_factory, run_id, "pareeksha.progress.v1")
    kinds = [(r.envelope["payload"]["kind"], r.envelope["payload"].get("status")) for r in progress]
    assert (
        kinds.count(("item.status", "cancelled")) == 3 and kinds.count(("run.completed", None)) == 1
    )

    again = await api.post(f"{API}/runs/{run_id}/cancel", headers=tenant.admin)
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize("final", ["completed", "partial", "failed"])
async def test_cancel_refuses_a_finished_run(
    api: AsyncClient, tenant: Tenant, session_factory: Factory, final: str
) -> None:
    fx = await make_fixture(api, tenant, 1, 1, 1)
    run_id = await _create(api, tenant, fx)
    async with session_factory() as session:
        await session.execute(
            update(models.TestRuns)
            .where(models.TestRuns.id == uuid.UUID(run_id))
            .values(status=final)
        )
        await session.commit()
    response = await api.post(f"{API}/runs/{run_id}/cancel", headers=tenant.admin)
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"status": final}
    still = (await api.get(f"{API}/runs/{run_id}", headers=tenant.read)).json()
    assert still["status"] == final


async def test_read_key_cannot_cancel(api: AsyncClient, tenant: Tenant) -> None:
    fx = await make_fixture(api, tenant, 1, 1, 1)
    run_id = await _create(api, tenant, fx)
    response = await api.post(f"{API}/runs/{run_id}/cancel", headers=tenant.read)
    assert response.status_code == 403
