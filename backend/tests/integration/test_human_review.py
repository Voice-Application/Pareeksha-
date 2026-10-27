"""T-FR-EV-7: per-dimension human scores stored; plus the calibration endpoint (FR-EV-8) and
re-evaluation (FR-EV-5 trigger) that share the same fixtures."""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.db import models
from pareeksha.evaluation.rubric import DIMENSION_KEYS, RUBRIC_VERSION
from pareeksha.evaluation.scoring import overall_score
from pareeksha.events.schemas import CallCompleted
from tests.conftest import Tenant
from tests.integration.domain import (
    API,
    build_world,
    dimensions,
    ensure_rubric,
    make_call,
    outbox_for,
)

FULL = {k: {"score": 3} for k in DIMENSION_KEYS}


async def test_review_stores_dimension_scores_and_computes_the_overall_in_code(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    call = await make_call(session_factory, world, score=88)
    body = {
        "reviewer": "preetham",
        "passed": False,
        "critical_failure": True,
        "dimensions": {**FULL, "factual_accuracy": {"score": 0}},
        "notes": "Agree with the judge's flag.",
    }
    response = await api.post(f"{API}/calls/{call.call_id}/review", json=body, headers=tenant.admin)
    assert response.status_code == 201, response.text
    out = response.json()
    assert out["evaluation_id"] == str(call.evaluation_id)
    assert (out["reviewer"], out["passed"], out["critical_failure"]) == ("preetham", False, True)
    assert out["dimensions"]["factual_accuracy"] == {"score": 0}
    assert out["dimensions"]["task_completion"] == {"score": 3}
    scores = {k: v["score"] for k, v in out["dimensions"].items()}
    assert out["overall_score"] == overall_score(scores) == 63.75  # 75 minus 15*(3/4)
    async with session_factory() as session:
        row = await session.scalar(
            select(models.HumanReviews).where(models.HumanReviews.id == uuid.UUID(out["id"]))
        )
        assert row is not None
        assert cast(dict[str, Any], row.dimensions)["factual_accuracy"] == {"score": 0}


async def test_partial_review_has_no_overall_and_validation(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    world = await build_world(api, tenant)
    call = await make_call(session_factory, world, score=60)
    url = f"{API}/calls/{call.call_id}/review"
    partial = await api.post(
        url,
        json={"reviewer": "a", "passed": True, "dimensions": {"task_completion": {"score": 4}}},
        headers=tenant.admin,
    )
    assert partial.status_code == 201 and partial.json()["overall_score"] is None
    dup = await api.post(url, json={"reviewer": "a", "passed": False}, headers=tenant.admin)
    assert dup.status_code == 409  # one review per reviewer and evaluation
    second = await api.post(url, json={"reviewer": "b", "passed": False}, headers=tenant.admin)
    assert second.status_code == 201
    unknown = await api.post(
        url,
        json={"reviewer": "c", "passed": True, "dimensions": {"charm": {"score": 1}}},
        headers=tenant.admin,
    )
    assert unknown.status_code == 400 and "charm" in unknown.json()["error"]["message"]
    out_of_range = await api.post(
        url,
        json={"reviewer": "c", "passed": True, "dimensions": {"escalation": {"score": 5}}},
        headers=tenant.admin,
    )
    assert out_of_range.status_code == 400
    assert (
        await api.post(url, json={"reviewer": "d", "passed": True}, headers=other_tenant.admin)
    ).status_code == 404
    assert (
        await api.post(url, json={"reviewer": "d", "passed": True}, headers=tenant.read)
    ).status_code == 403
    unevaluated = await make_call(session_factory, world, score=None)
    none = await api.post(
        f"{API}/calls/{unevaluated.call_id}/review",
        json={"reviewer": "a", "passed": True},
        headers=tenant.admin,
    )
    assert none.status_code == 409
    missing = await api.post(
        f"{API}/calls/{uuid.uuid4()}/review",
        json={"reviewer": "a", "passed": True},
        headers=tenant.admin,
    )
    assert missing.status_code == 404


async def _review(
    api: AsyncClient,
    tenant: Tenant,
    call_id: uuid.UUID,
    passed: bool,
    dims: dict[str, int],
    reviewer: str = "preetham",
) -> None:
    body = {
        "reviewer": reviewer,
        "passed": passed,
        "dimensions": {k: {"score": v} for k, v in dims.items()},
    }
    response = await api.post(f"{API}/calls/{call_id}/review", json=body, headers=tenant.admin)
    assert response.status_code == 201, response.text


def _full(score: int, **override: int) -> dict[str, int]:
    return {k: override.get(k, score) for k in DIMENSION_KEYS}


async def test_calibration_endpoint_matches_hand_computed_agreement(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    empty = (await api.get(f"{API}/calibration", headers=tenant.read)).json()
    assert empty == {"n": 0, "kappa_pass_fail": None, "spearman_overall": None, "dimension_mae": {}}

    world = await build_world(api, tenant)
    # (judge score, judge dims, human passed, human dims); judge passes when score >= 80
    cases = [
        (92, _full(4), True, _full(4)),
        (85, _full(3, task_completion=4), True, _full(3)),
        (60, _full(2), False, _full(1, task_completion=2)),
        (82, _full(3), False, _full(2)),  # judge pass, human fail
    ]
    for score, jdims, hpass, hdims in cases:
        call = await make_call(session_factory, world, score=score, judge_dims=dimensions(**jdims))
        await _review(api, tenant, call.call_id, hpass, hdims)
    # a call without a human review, and another project's reviewed call, must not count
    await make_call(session_factory, world, score=10)
    foreign = await build_world(api, other_tenant)
    other = await make_call(session_factory, foreign, score=50)
    await _review(api, other_tenant, other.call_id, True, _full(4))

    out = (await api.get(f"{API}/calibration", headers=tenant.read)).json()
    assert out["n"] == 4
    # judge pass/fail T T F T vs human T T F F: observed 3/4; chance .75*.5 + .25*.5 = .5; kappa .5
    assert out["kappa_pass_fail"] == 0.5
    # judge overall 92 85 60 82 vs human overall = 100, 75, 31.25 (task 2, rest 1), 50
    # (weighted from the 0-4 scores): ranks judge 4 3 1 2, human 4 3 1 2 -> spearman 1
    assert out["spearman_overall"] == 1.0
    mae = out["dimension_mae"]
    assert mae["task_completion"] == pytest.approx((0 + 1 + 0 + 1) / 4)  # |4-4| |4-3| |2-2| |3-2|
    assert mae["escalation"] == pytest.approx((0 + 0 + 1 + 1) / 4)  # |4-4| |3-3| |2-1| |3-2|

    versioned = (
        await api.get(
            f"{API}/calibration", params={"rubric_version": RUBRIC_VERSION}, headers=tenant.read
        )
    ).json()
    assert versioned == out
    unknown = (
        await api.get(f"{API}/calibration", params={"rubric_version": "nope"}, headers=tenant.read)
    ).json()
    assert unknown["n"] == 0
    assert (await api.get(f"{API}/calibration", headers=other_tenant.read)).json()["n"] == 1


async def test_reevaluate_enqueues_a_fresh_call_completed(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ensure_rubric(session_factory)
    world = await build_world(api, tenant)
    call = await make_call(session_factory, world, score=50)
    url = f"{API}/calls/{call.call_id}/reevaluate"
    first = await api.post(url, headers=tenant.admin)
    assert first.status_code == 202 and first.json() == {"call_id": str(call.call_id)}
    second = await api.post(url, json={"rubric_version": RUBRIC_VERSION}, headers=tenant.admin)
    assert second.status_code == 202
    ours = await outbox_for(session_factory, "call_id", str(call.call_id))
    assert len(ours) == 2 and ours[0].event_id != ours[1].event_id  # two requests, two events
    payload = ours[0].payload
    assert isinstance(payload, CallCompleted)
    assert (payload.source, payload.agent_id, payload.run_id, payload.run_item_id) == (
        "simulation",
        world.agent_id,
        call.run_id,
        call.run_item_id,
    )
    assert ours[0].topic.value == "pareeksha.call.completed.v1"

    unknown = await api.post(url, json={"rubric_version": "nope"}, headers=tenant.admin)
    assert unknown.status_code == 404
    async with session_factory() as session:
        session.add(models.RubricVersions(version="rubric-future", dimensions={}, prompt_hash="x"))
        await session.commit()
    unsupported = await api.post(
        url, json={"rubric_version": "rubric-future"}, headers=tenant.admin
    )
    assert unsupported.status_code == 400
    running = await make_call(session_factory, world, score=None, call_status="in_progress")
    busy = await api.post(f"{API}/calls/{running.call_id}/reevaluate", headers=tenant.admin)
    assert busy.status_code == 409
    assert (await api.post(url, headers=other_tenant.admin)).status_code == 404
    assert (await api.post(url, headers=tenant.read)).status_code == 403
