"""T-FR-RG-2: regression suite run and verdict (score >= baseline - tolerance, no critical)."""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.db import models
from pareeksha.evaluation.handlers import RunState, summarize_run
from pareeksha.events.schemas import RunRequested
from pareeksha.regression.outcomes import run_outcomes
from tests.conftest import Tenant
from tests.integration.domain import (
    API,
    build_world,
    make_call,
    make_regression_test,
    make_run,
    outbox_for,
)


async def _suite_verdict(
    factory: async_sessionmaker[AsyncSession], run_id: uuid.UUID, agent_id: uuid.UUID
) -> bool | None:
    async with factory() as session:
        items = await run_outcomes(session, run_id)
    return summarize_run(RunState(run_id, agent_id, "regression", "running", items)).suite_passed


async def test_run_regression_creates_run_and_outbox_event(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    await make_regression_test(session_factory, world, status="blocking")
    await make_regression_test(session_factory, world, status="blocking", failure_type="loop")
    await make_regression_test(session_factory, world, status="manual", failure_type="x")
    await make_regression_test(session_factory, world, status="retired", failure_type="y")

    response = await api.post(
        f"{API}/runs:regression",
        json={"agent_id": str(world.agent_id), "config": {"max_concurrency": 2, "seed": 7}},
        headers=tenant.admin,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued" and body["item_count"] == 2  # blocking only by default
    assert body["estimate"]["judge_calls"] == 2

    run_id = uuid.UUID(body["id"])
    async with session_factory() as session:
        run = await session.get(models.TestRuns, run_id)
        assert run is not None
        assert (run.kind, run.status, run.agent_id) == ("regression", "queued", world.agent_id)
        assert run.config == {
            "max_concurrency": 2,
            "seed": 7,
            "dry_run": False,
            "statuses": ["blocking"],
        }
        snapshot = cast(dict[str, Any], run.agent_snapshot)
        assert snapshot["name"].startswith("EMI Bot")
        assert "adapter_secrets_encrypted" not in snapshot
    ours = await outbox_for(session_factory, "run_id", str(run_id))
    assert len(ours) == 1
    payload = ours[0].payload
    assert isinstance(payload, RunRequested)
    assert (payload.kind, payload.regression_statuses, payload.seed) == (
        "regression",
        ["blocking"],
        7,
    )
    assert ours[0].topic.value == "pareeksha.run.requested.v1"
    assert ours[0].partition_key() == str(run_id)

    both = await api.post(
        f"{API}/runs:regression",
        json={"agent_id": str(world.agent_id), "statuses": ["blocking", "manual"]},
        headers=tenant.admin,
    )
    assert both.json()["item_count"] == 3


async def test_run_regression_errors(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    world = await build_world(api, tenant)
    url = f"{API}/runs:regression"
    none = await api.post(url, json={"agent_id": str(world.agent_id)}, headers=tenant.admin)
    assert none.status_code == 409 and "no regression tests" in none.json()["error"]["message"]
    ghost = await api.post(url, json={"agent_id": str(uuid.uuid4())}, headers=tenant.admin)
    assert ghost.status_code == 404
    await make_regression_test(session_factory, world)
    foreign = await api.post(
        url, json={"agent_id": str(world.agent_id)}, headers=other_tenant.admin
    )
    assert foreign.status_code == 404
    read_only = await api.post(url, json={"agent_id": str(world.agent_id)}, headers=tenant.read)
    assert read_only.status_code == 403
    bad = await api.post(
        url, json={"agent_id": str(world.agent_id), "statuses": []}, headers=tenant.admin
    )
    assert bad.status_code == 400


async def test_budget_check_refuses_with_the_estimate_unless_confirmed(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await build_world(api, tenant)
    await make_regression_test(session_factory, world)
    monkeypatch.setenv("COST_STT_STREAM_PER_MIN", "10")
    monkeypatch.setenv("COST_TTS_PER_1K_CHARS", "5")
    monkeypatch.setenv("BUDGET_CREDITS", "0.5")
    body = {"agent_id": str(world.agent_id)}
    refused = await api.post(f"{API}/runs:regression", json=body, headers=tenant.admin)
    assert refused.status_code == 402, refused.text
    error = refused.json()["error"]
    assert error["code"] == "budget_exceeded"
    assert error["details"]["estimate"]["est_cost"] > 0.5
    assert error["details"]["remaining_budget"] <= 0.5
    forced = await api.post(
        f"{API}/runs:regression", json={**body, "confirm_over_budget": True}, headers=tenant.admin
    )
    assert forced.status_code == 201
    monkeypatch.setenv("BUDGET_CREDITS", "1000000")
    assert (
        await api.post(f"{API}/runs:regression", json=body, headers=tenant.admin)
    ).status_code == 201


async def test_suite_fails_when_any_blocking_test_scores_below_baseline_minus_tolerance(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    steady = await make_regression_test(session_factory, world, baseline=80, tolerance=5)
    flaky = await make_regression_test(
        session_factory, world, baseline=90, tolerance=5, failure_type="loop"
    )
    manual = await make_regression_test(
        session_factory, world, status="manual", baseline=99, failure_type="x"
    )
    run = await make_run(session_factory, world)
    await make_call(session_factory, world, run_id=run, regression_test_id=steady, score=76)
    await make_call(session_factory, world, run_id=run, regression_test_id=flaky, score=85)
    await make_call(session_factory, world, run_id=run, regression_test_id=manual, score=10)
    assert await _suite_verdict(session_factory, run, world.agent_id) is True  # 76>=75, 85>=85

    failing = await make_run(session_factory, world)
    await make_call(session_factory, world, run_id=failing, regression_test_id=steady, score=90)
    await make_call(session_factory, world, run_id=failing, regression_test_id=flaky, score=84.9)
    assert await _suite_verdict(session_factory, failing, world.agent_id) is False  # 84.9 < 85

    critical = await make_run(session_factory, world)
    await make_call(
        session_factory, world, run_id=critical, regression_test_id=steady, score=99, critical=True
    )
    assert await _suite_verdict(session_factory, critical, world.agent_id) is False

    errored = await make_run(session_factory, world)
    await make_call(
        session_factory,
        world,
        run_id=errored,
        regression_test_id=steady,
        score=None,
        item_status="error",
        call_status="error",
    )
    assert await _suite_verdict(session_factory, errored, world.agent_id) is False


async def test_list_shows_last_result_per_test(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    test = await make_regression_test(session_factory, world, baseline=80, tolerance=5)
    fresh = (await api.get(f"{API}/regression-tests", headers=tenant.read)).json()["items"][0]
    assert (fresh["last_run_id"], fresh["last_score"], fresh["last_passed"]) == (None, None, None)

    old = await make_call(session_factory, world, regression_test_id=test, score=95)
    newest = await make_call(session_factory, world, regression_test_id=test, score=70)
    item = (await api.get(f"{API}/regression-tests", headers=tenant.read)).json()["items"][0]
    assert item["last_run_id"] == str(newest.run_id) != str(old.run_id)
    assert (item["last_score"], item["last_passed"]) == (70, False)  # 70 < 80 - 5
    # relaxing the baseline re-judges the same result
    await api.patch(
        f"{API}/regression-tests/{test}", json={"baseline_score": 72}, headers=tenant.admin
    )
    relaxed = (await api.get(f"{API}/regression-tests", headers=tenant.read)).json()["items"][0]
    assert (relaxed["last_score"], relaxed["last_passed"]) == (70, True)  # 70 >= 72 - 5
