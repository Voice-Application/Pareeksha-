"""GET /runs/compare and GET /runs/{id}/report (API-04, FR-RG-3). Real app, real Postgres."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.conftest import Tenant, new_tenant
from tests.integration.api04_support import Factory, new_rubric, seed_run
from tests.integration.runs_support import API, make_fixture


async def test_compare_gives_per_cell_deltas_and_summary(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    fx = await make_fixture(api, tenant, scenarios=5, personas=1, profiles=1)
    rubric = await new_rubric(session_factory)
    #            cell:  0 down+fails  1 down, still passes  2 up  3 same  4 only scored in base
    base = await seed_run(
        api, session_factory, tenant, fx=fx, rubric_id=rubric,
        scores=[(86, True), (95, True), (40, False), (70, False), (60, False)],
    )  # fmt: skip
    head = await seed_run(
        api, session_factory, tenant, fx=fx, rubric_id=rubric,
        scores=[(52, False), (85, True), (72.5, False), (70, False), None],
    )  # fmt: skip
    response = await api.get(
        f"{API}/runs/compare",
        params={"base": str(base.run_id), "head": str(head.run_id)},
        headers=tenant.read,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == {"regressed": 2, "improved": 1, "unchanged": 1}
    cells = body["cells"]
    assert len(cells) == 5
    # worst delta first, a cell with no delta last
    assert [c["delta"] for c in cells] == [-34.0, -10.0, 0.0, 32.5, None]
    first = cells[0]
    assert first["scenario"].startswith("Scenario 0") and first["persona"].startswith("Persona 0")
    assert first["profile"].startswith("profile_0_")
    assert (first["base_score"], first["head_score"]) == (86.0, 52.0)
    assert first["newly_failing"] is True
    by_delta = {c["delta"]: c for c in cells}
    assert by_delta[-10.0]["newly_failing"] is False  # got worse but still passes
    assert by_delta[32.5]["newly_failing"] is False  # improved
    assert by_delta[0.0]["newly_failing"] is False  # failed in both: not *newly* failing
    unscored = cells[-1]
    assert (unscored["base_score"], unscored["head_score"]) == (60.0, None)
    assert unscored["newly_failing"] is False


async def test_compare_of_a_run_with_itself_and_with_repeats(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    fx = await make_fixture(api, tenant, scenarios=1, personas=1, profiles=1)
    rubric = await new_rubric(session_factory)
    # two repeats of one cell: mean score, passed only if both passed
    base = await seed_run(
        api, session_factory, tenant, fx=fx, rubric_id=rubric, scores=[(80, True), (100, True)]
    )
    head = await seed_run(
        api, session_factory, tenant, fx=fx, rubric_id=rubric, scores=[(90, True), (50, False)]
    )
    body = (
        await api.get(
            f"{API}/runs/compare", params={"base": str(base.run_id), "head": str(head.run_id)},
            headers=tenant.read,
        )
    ).json()  # fmt: skip
    assert len(body["cells"]) == 1
    cell = body["cells"][0]
    assert (cell["base_score"], cell["head_score"], cell["delta"]) == (90.0, 70.0, -20.0)
    assert cell["newly_failing"] is True
    same = (
        await api.get(
            f"{API}/runs/compare", params={"base": str(base.run_id), "head": str(base.run_id)},
            headers=tenant.read,
        )
    ).json()  # fmt: skip
    assert same["summary"] == {"regressed": 0, "improved": 0, "unchanged": 1}


async def test_compare_unknown_foreign_and_invalid(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    mine = await seed_run(api, session_factory, tenant, scores=[(80, True)])
    other = await new_tenant(session_factory)
    theirs = await seed_run(api, session_factory, other, scores=[(80, True)])
    for base, head in ((mine.run_id, uuid.uuid4()), (mine.run_id, theirs.run_id)):
        r = await api.get(
            f"{API}/runs/compare",
            params={"base": str(base), "head": str(head)},
            headers=tenant.read,
        )
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    bad = await api.get(
        f"{API}/runs/compare", params={"base": "x", "head": "y"}, headers=tenant.read
    )
    assert bad.status_code == 400
    missing = await api.get(
        f"{API}/runs/compare", params={"base": str(mine.run_id)}, headers=tenant.read
    )
    assert missing.status_code == 400
    assert (
        await api.get(f"{API}/runs/compare?base={mine.run_id}&head={mine.run_id}")
    ).status_code == 401


async def test_report_is_a_self_contained_escaped_html_page(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    summary = {
        "pass_rate": 0.5, "critical_failures": 1, "score_mean": 61.25, "latency_p95_ms": 2310,
        "top_failure_types": [["asr_misrecognition", 2]],
        "score_distribution": [0, 0, 0, 0, 1, 0, 0, 1, 0, 0],
    }  # fmt: skip
    seeded = await seed_run(
        api, session_factory, tenant, scores=[(90, True), (32.5, False)], summary=summary
    )
    response = await api.get(f"{API}/runs/{seeded.run_id}/report", headers=tenant.read)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert html.startswith("<!doctype html>") and "<script" not in html and "http" not in html
    assert "seeded run" in html and str(seeded.run_id) in html
    for expected in ("50%", "61.2", "2310 ms", "asr_misrecognition: 2", "90.0", "32.5", "40-49"):
        assert expected in html
    assert html.count("<tr><td>Scenario") == 2


async def test_report_escapes_names_and_handles_unfinished_runs(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    fx = await make_fixture(api, tenant, scenarios=1, personas=1, profiles=1)
    evil = "<img src=x onerror=alert(1)>"
    patched = await api.patch(
        f"{API}/scenarios/{fx.scenario_ids[0]}", json={"title": evil}, headers=tenant.admin
    )
    assert patched.status_code == 200, patched.text
    seeded = await seed_run(api, session_factory, tenant, fx=fx, scores=[None], status="running")
    html = (await api.get(f"{API}/runs/{seeded.run_id}/report", headers=tenant.read)).text
    assert evil not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "n/a" in html  # no summary yet
    assert (
        await api.get(f"{API}/runs/{uuid.uuid4()}/report", headers=tenant.read)
    ).status_code == 404
