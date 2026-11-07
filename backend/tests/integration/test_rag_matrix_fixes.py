"""RAG matrix review fixes: unique entry labels, and the budget ignores entries that never run."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.rag import matrix as matrix_mod
from pareeksha.runs import service
from pareeksha.runs.service import Prepared
from pareeksha.schemas.runs import RunCreate
from tests.conftest import Tenant
from tests.integration.runs_support import API
from tests.integration.test_rag_matrix_api import MATRICES, add_index, env, setup  # noqa: F401


async def test_identical_configs_get_unique_labels(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    s = await setup(api, tenant, database_url)
    same = s.cfg()  # no label: all three share the auto label
    await add_index(s, same, 1)
    named = s.cfg(label="Full context")  # collides with a baseline's label too
    r = await api.post(MATRICES, json=s.body([same, same, same, named]), headers=tenant.admin)
    assert r.status_code == 201, r.text
    labels = [e["label"] for e in r.json()["entries"]]
    auto = labels[2]
    assert labels == [
        "No RAG",
        "Full context",
        auto,
        f"{auto} (2)",
        f"{auto} (3)",
        "Full context (2)",
    ]
    assert len(set(labels)) == len(labels)
    for e in r.json()["entries"]:  # each entry has its own run, named after its unique label
        run = await api.get(f"{API}/runs/{e['run_id']}", headers=tenant.read)
        assert run.json()["name"] == f"RAG · {e['label']}"
    assert len({e["run_id"] for e in r.json()["entries"]}) == len(labels)


async def test_budget_estimate_excludes_the_na_baseline(
    api: AsyncClient, tenant: Tenant, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await setup(api, tenant, database_url, chars=5000)
    a = s.cfg(label="a", context_char_limit=1000)  # the 5000-char KB does not fit: n/a
    await add_index(s, a, 1)

    prepare = service.prepare

    async def priced(session: AsyncSession, project_id: uuid.UUID, req: RunCreate) -> Prepared:
        p = await prepare(session, project_id, req)
        cost = 10.0 if "Full context" in req.name else 1.0
        p.estimate = p.estimate.model_copy(update={"est_cost": cost})
        return p

    totals: list[float] = []
    monkeypatch.setattr(service, "prepare", priced)
    monkeypatch.setattr(matrix_mod, "is_over_budget", lambda total, remaining: totals.append(total))
    r = await api.post(MATRICES, json=s.body([a]), headers=tenant.admin)
    assert r.status_code == 201, r.text
    by_label = {e["label"]: e for e in r.json()["entries"]}
    assert by_label["Full context"]["run_id"] is None  # n/a: no run
    assert totals == [2.0]  # No RAG + "a"; the 10.0 of the baseline that never runs is not counted
