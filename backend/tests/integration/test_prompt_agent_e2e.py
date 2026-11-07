"""A prompt agent end to end: version -> run -> text call -> checks -> judge -> compare.

Real app and Postgres; the agent model, the simulated caller and the judge are scripted. The
workers' handlers are driven directly (no Kafka), as in ``test_simulator_worker.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient

from pareeksha.events.runtime import Database
from pareeksha.events.schemas import CallCompleted, CallRequested, make_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.storage.blob import LocalBlobStore
from pareeksha.workers import evaluator, simulator
from tests.conftest import Tenant
from tests.integration.audit_support import fetch_rows, transaction
from tests.integration.eval_support import seed_rubric
from tests.integration.runs_support import API, make_fixture, plan_in_db, settings_for
from tests.unit.evaluation.fakes import ScriptedProvider, judge_json
from tests.unit.simulation.simfakes import ScriptedCaller
from tests.unit.simulation.test_text_runner import FakeChat, call, text, tools_reply

KEY = "sk-e2e-secret"
EXPECTED = [{"name": "lookup_emi"}, {"name": "waive_fee", "expect": "not_called"}]
LOOKUP = {
    "name": "lookup_emi",
    "description": "Look up the customer's EMI",
    "parameters": {"type": "object", "properties": {}},
    "mock": {"mode": "static", "result": {"emi": 4200}},
}
WAIVE = {
    "name": "waive_fee",
    "description": "Waive the late fee",
    "parameters": {"type": "object", "properties": {}},
    "mock": {"mode": "static", "result": {"waived": True}},
}


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())


@pytest.fixture
async def workers(database_url: str, tmp_path: Any) -> AsyncIterator[Database]:
    settings = settings_for(database_url)
    db = Database(settings)
    usage = ApiUsageSink(settings)
    simulator.configure(db=db, usage=usage, blobs=LocalBlobStore(tmp_path))
    yield db
    simulator.configure()
    evaluator.set_client(None)
    await db.close()
    await usage.close()


async def _run_version(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
    agent_chat: FakeChat,
) -> str:
    """Create a run for the active version, simulate its call, evaluate it; returns the run id."""
    created = await api.post(f"{API}/runs", json=body, headers=tenant.admin)
    assert created.status_code == 201, created.text
    run_id: str = created.json()["id"]
    (req,) = [
        o.payload
        for o in await plan_in_db(database_url, run_id)
        if isinstance(o.payload, CallRequested)
    ]

    keys: list[str | None] = []

    def build(provider: str, *, api_key: str | None = None, base_url: str | None = None) -> Any:
        keys.append(api_key)
        return agent_chat

    monkeypatch.setattr(simulator, "build_chat_provider", build)
    monkeypatch.setattr(simulator, "_caller", ScriptedCaller(["What is my EMI?"]))
    env = make_envelope(req, producer="planner", correlation_id=run_id)
    async with transaction(database_url) as ctx:
        (out,) = await simulator.on_call_requested(env, ctx)
    assert isinstance(out.payload, CallCompleted)
    assert keys == [KEY]  # the saved key reached the provider factory

    usage = ApiUsageSink(settings_for(database_url))
    settings = LLMSettings(_env_file=None, deepseek_api_key="k")
    judge = LLMClient(ScriptedProvider([judge_json()]), settings, usage_sink=usage)
    evaluator.set_client(judge, usage, db)
    done = make_envelope(out.payload, producer="simulator", correlation_id=run_id)
    try:
        async with transaction(database_url) as ctx:
            await evaluator.on_call_completed(done, ctx)
    finally:
        await usage.close()
    return run_id


async def _checks(database_url: str, run_id: str) -> dict[tuple[str, str], bool | None]:
    """The run's deterministic check results, keyed by ``(check_type, check_key)``."""
    rows = await fetch_rows(
        database_url,
        "SELECT c.check_type, c.check_key, c.passed FROM deterministic_checks c "
        "JOIN calls ON calls.id = c.call_id JOIN run_items i ON i.id = calls.run_item_id "
        "WHERE i.run_id = %s",
        run_id,
    )
    return {(r["check_type"], r["check_key"]): r["passed"] for r in rows}


async def test_prompt_agent_flow_and_version_compare(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    workers: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two prompt versions run end to end; v2 calls a tool it must not, so compare flags it.

    Covers the transcript, the mocked tool trace, the tool checks and the v1 to v2 compare with the
    prompt versions each run pinned.
    """
    fx = await make_fixture(api, tenant, 0, 1, 1)
    await _seed(database_url)

    created = await api.post(
        f"{API}/agents",
        json={"name": "refund-bot", "adapter": "prompt", "adapter_secrets": {"api_key": KEY}},
        headers=tenant.admin,
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert KEY not in created.text

    def version(tools: list[dict[str, Any]], prompt: str) -> dict[str, Any]:
        return {
            "system_prompt": prompt,
            "provider": "openai",
            "model": "gpt-x",
            "tools": tools,
        }

    scenario = await api.post(
        f"{API}/scenarios",
        json={
            "title": "EMI question",
            "caller_goal": "Ask what the EMI is.",
            "success_criteria": "The agent states the EMI.",
            "max_turns": 2,
            "agent_id": agent["id"],
            "expected_tool_calls": EXPECTED,
        },
        headers=tenant.admin,
    )
    assert scenario.status_code == 201, scenario.text
    body = {
        "agent_id": agent["id"],
        "name": "prompt run",
        "scenario_ids": [scenario.json()["id"]],
        "persona_ids": fx.persona_ids,
        "noise_profile_ids": fx.noise_profile_ids,
    }

    # v1 looks the EMI up and does nothing else
    v1 = await api.post(
        f"{API}/agents/{agent['id']}/prompt-versions",
        json=version([LOOKUP, WAIVE], "Answer EMI questions."),
        headers=tenant.admin,
    )
    assert v1.status_code == 201 and v1.json()["version"] == 1, v1.text
    chat1 = FakeChat([tools_reply(call("lookup_emi")), text("Your EMI is 4200.")])
    run1 = await _run_version(api, tenant, database_url, workers, monkeypatch, body, chat1)

    turns = await fetch_rows(
        database_url,
        "SELECT t.speaker, t.text FROM turns t JOIN calls c ON c.id = t.call_id "
        "JOIN run_items i ON i.id = c.run_item_id WHERE i.run_id = %s ORDER BY t.idx",
        run1,
    )
    assert [t["speaker"] for t in turns][:2] == ["caller", "agent"]
    assert turns[1]["text"] == "Your EMI is 4200."
    assert chat1.seen[0][0].content == "Answer EMI questions."  # the system prompt under test
    tools = await fetch_rows(
        database_url,
        "SELECT t.name, t.result FROM tool_calls t JOIN calls c ON c.id = t.call_id "
        "JOIN run_items i ON i.id = c.run_item_id WHERE i.run_id = %s",
        run1,
    )
    assert tools == [{"name": "lookup_emi", "result": {"emi": 4200}}]
    checks1 = await _checks(database_url, run1)
    assert checks1[("tool_calls_expected", "lookup_emi")] is True
    assert checks1[("tool_calls_expected", "not_called:waive_fee")] is True
    assert checks1[("no_unexpected_tool", "no_unexpected_tool")] is True

    # v2 also waives the fee: the not_called expectation fails
    v2 = await api.post(
        f"{API}/agents/{agent['id']}/prompt-versions",
        json=version([LOOKUP, WAIVE], "Answer EMI questions and be generous."),
        headers=tenant.admin,
    )
    assert v2.status_code == 201 and v2.json()["version"] == 2, v2.text
    chat2 = FakeChat(
        [tools_reply(call("lookup_emi"), call("waive_fee")), text("Done, fee waived.")]
    )
    run2 = await _run_version(api, tenant, database_url, workers, monkeypatch, body, chat2)
    checks2 = await _checks(database_url, run2)
    assert checks2[("tool_calls_expected", "lookup_emi")] is True
    assert checks2[("tool_calls_expected", "not_called:waive_fee")] is False
    assert checks2[("no_unexpected_tool", "waive_fee#2")] is False

    # compare: v1 -> v2, and the old run still points at v1 although v2 is now active
    cmp = await api.get(
        f"{API}/runs/compare", params={"base": run1, "head": run2}, headers=tenant.read
    )
    assert cmp.status_code == 200, cmp.text
    out = cmp.json()
    assert (out["base_prompt_version"], out["head_prompt_version"]) == (1, 2)
    (cell,) = out["cells"]
    assert len(cell["base_call_ids"]) == 1 and len(cell["head_call_ids"]) == 1
    # the scripted judge scores both calls alike, but the failed must-pass tool check fails v2
    assert cell["base_score"] == cell["head_score"]
    assert cell["newly_failing"] is True


async def _seed(database_url: str) -> None:
    with psycopg.connect(libpq_url(database_url), autocommit=True) as conn:
        seed_rubric(conn)
