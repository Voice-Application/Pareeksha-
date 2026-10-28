"""T-FR-RG-1: status, failure type, baseline and tolerance are stored and editable."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import Tenant
from tests.integration.domain import API, build_world, make_regression_test


async def test_fields_filters_and_patch(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    blocking = await make_regression_test(session_factory, world, status="blocking", baseline=85)
    await make_regression_test(session_factory, world, status="manual", failure_type="loop")
    other_world = await build_world(api, tenant)
    await make_regression_test(session_factory, other_world, status="blocking")

    mine = (
        await api.get(
            f"{API}/regression-tests", params={"agent_id": str(world.agent_id)}, headers=tenant.read
        )
    ).json()["items"]
    assert sorted(t["status"] for t in mine) == ["blocking", "manual"]
    only = (
        await api.get(
            f"{API}/regression-tests",
            params={"agent_id": str(world.agent_id), "status": "blocking"},
            headers=tenant.read,
        )
    ).json()["items"]
    assert [t["id"] for t in only] == [str(blocking)]
    assert only[0]["scenario_title"] == "Already paid, wants confirmation"
    assert (only[0]["baseline_score"], only[0]["tolerance"]) == (85, 5)
    assert only[0]["failure_type"] == "wrong_fact"

    url = f"{API}/regression-tests/{blocking}"
    patched = await api.patch(
        url,
        json={"status": "scheduled", "baseline_score": 70.5, "tolerance": 2, "notes": "relaxed"},
        headers=tenant.admin,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert (body["status"], body["baseline_score"], body["tolerance"], body["notes"]) == (
        "scheduled",
        70.5,
        2,
        "relaxed",
    )
    partial = await api.patch(url, json={"status": "retired"}, headers=tenant.admin)
    assert (partial.json()["status"], partial.json()["baseline_score"]) == ("retired", 70.5)
    kept = await api.patch(url, json={"notes": None}, headers=tenant.admin)  # null = unchanged
    assert kept.json()["notes"] == "relaxed"


@pytest.mark.parametrize(
    "body",
    [
        {"status": "paused"},
        {"baseline_score": 101},
        {"baseline_score": -1},
        {"tolerance": 101},
        {"unknown": 1},
    ],
)
async def test_patch_rejects_invalid_values(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    body: dict[str, object],
) -> None:
    world = await build_world(api, tenant)
    test = await make_regression_test(session_factory, world)
    response = await api.patch(f"{API}/regression-tests/{test}", json=body, headers=tenant.admin)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_scopes_and_project_isolation(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    world = await build_world(api, tenant)
    test = await make_regression_test(session_factory, world)
    url = f"{API}/regression-tests/{test}"
    assert (await api.patch(url, json={"notes": "x"}, headers=tenant.read)).status_code == 403
    assert (
        await api.patch(url, json={"notes": "x"}, headers=other_tenant.admin)
    ).status_code == 404
    assert (
        await api.patch(
            f"{API}/regression-tests/{uuid.uuid4()}", json={"notes": "x"}, headers=tenant.admin
        )
    ).status_code == 404
    assert (await api.get(f"{API}/regression-tests", headers=other_tenant.read)).json()[
        "items"
    ] == []
