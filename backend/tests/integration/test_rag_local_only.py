"""A local-only knowledge base: no test run may start, because the transcript (built from KB text)
would reach Pareeksha's hosted caller brain and judge."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from pareeksha.events.runtime import Database
from pareeksha.events.schemas import CallRequested, make_envelope
from pareeksha.rag.guard import PLATFORM_LLM_REFUSAL
from pareeksha.workers import simulator
from tests.conftest import Tenant
from tests.integration import test_rag_matrix_api as matrix_tests
from tests.integration.audit_support import fetch_rows, transaction
from tests.integration.runs_support import API, plan_in_db
from tests.integration.test_rag_runs import (  # noqa: F401  (fixtures)
    KB,
    add_index,
    env,
    setup,
    workers,
)
from tests.unit.simulation.simfakes import ScriptedCaller
from tests.unit.simulation.test_text_runner import FakeChat, text

MODES = ["retrieval", "full_context", "off"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("override", [False, True], ids=["version-config", "run-override"])
async def test_run_refused_for_a_local_only_kb(
    api: AsyncClient, tenant: Tenant, database_url: str, mode: str, override: bool
) -> None:
    # a local agent and no index: only the platform-LLM rule can be what refuses it
    s = await setup(
        api,
        tenant,
        database_url,
        local_only=True,
        provider="ollama",
        rag=None if override else {"mode": mode},
        run_rag={"mode": mode} if override else None,
    )
    r = await api.post(f"{API}/runs", json=s.body, headers=tenant.admin)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "local_only"
    assert r.json()["error"]["message"] == PLATFORM_LLM_REFUSAL
    runs = await api.get(
        f"{API}/runs", params={"agent_id": s.body["agent_id"]}, headers=tenant.read
    )
    assert runs.json()["items"] == []


async def test_matrix_refused_for_a_local_only_kb(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    s = await matrix_tests.setup(api, tenant, database_url)
    cfg = s.cfg(label="a")
    await matrix_tests.add_index(s, cfg, 1)
    patched = await api.patch(
        f"{API}/knowledge-bases/{s.kb_id}", json={"local_only": True}, headers=tenant.admin
    )
    assert patched.status_code == 200, patched.text
    r = await api.post(matrix_tests.MATRICES, json=s.body([cfg]), headers=tenant.admin)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "local_only"
    assert r.json()["error"]["message"] == PLATFORM_LLM_REFUSAL
    runs = await api.get(f"{API}/runs", params={"agent_id": s.agent_id}, headers=tenant.read)
    assert runs.json()["items"] == []  # nothing was written, baselines included


@pytest.mark.parametrize("mode", ["retrieval", "off"])
async def test_local_only_switched_on_after_run_creation_sends_nothing(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    workers: Database,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    s = await setup(api, tenant, database_url, provider="ollama", rag={"mode": mode})
    if mode == "retrieval":
        await add_index(database_url, s, "Refunds take seven days.", version=1)
    created = await api.post(f"{API}/runs", json=s.body, headers=tenant.admin)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    flipped = await api.patch(f"{KB}/{s.kb_id}", json={"local_only": True}, headers=tenant.admin)
    assert flipped.status_code == 200, flipped.text

    (req,) = [
        o.payload
        for o in await plan_in_db(database_url, run_id)
        if isinstance(o.payload, CallRequested)
    ]
    chat, caller = FakeChat([text("Seven days.")]), ScriptedCaller(["How long do refunds take?"])
    monkeypatch.setattr(simulator, "build_chat_provider", lambda *a, **k: chat)
    monkeypatch.setattr(simulator, "_caller", caller)
    async with transaction(database_url) as ctx:
        out = await simulator.on_call_requested(
            make_envelope(req, producer="planner", correlation_id=run_id), ctx
        )
    assert out == []  # connect_failed: nothing for the evaluator
    assert caller.histories == [] and chat.seen == []  # no hosted caller, no agent call
    (call,) = await fetch_rows(
        database_url,
        "SELECT c.end_reason, c.error, c.status FROM calls c "
        "JOIN run_items i ON i.id = c.run_item_id WHERE i.run_id = %s",
        run_id,
    )
    assert call == {"end_reason": "connect_failed", "error": "local_only", "status": "error"}
    turns = await fetch_rows(
        database_url,
        "SELECT t.idx FROM turns t JOIN calls c ON c.id = t.call_id "
        "JOIN run_items i ON i.id = c.run_item_id WHERE i.run_id = %s",
        run_id,
    )
    assert turns == []
