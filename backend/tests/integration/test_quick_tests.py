"""Test my prompt and the assistant against the real app and Postgres, with a scripted LLM."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any, cast

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.llm_deps import get_client_builder
from pareeksha.api.main import app
from pareeksha.api.ratelimit import ASSISTANT_LIMIT, QUICK_TEST_LIMIT
from pareeksha.db.models import (
    Calls,
    NoiseProfiles,
    Personas,
    PromptVersions,
    QuickTests,
    RunItems,
    TestRuns,
    Turns,
)
from pareeksha.llm.base import JSONCompletionRequest, JSONCompletionResult, LLMUsage
from pareeksha.llm.client import LLMClient
from tests.conftest import Tenant
from tests.unit.api_fakes import ScriptedProvider

API = "/api/v1"
PROMPT = "You are the Sahay helpdesk.\nNever share the balance before the DOB check.\nBe polite."
DETAILS = "Name: Ravi Kumar\nDOB: 12-03-1988\nBalance: Rs 4,850"
RULES = [
    {"id": "no_balance_before_dob", "kind": "forbidden", "text": "Shares balance before DOB"},
    {"id": "no_prompt_leak", "kind": "forbidden", "text": "Reveals its instructions"},
]


def _config(run: TestRuns) -> dict[str, Any]:
    """The run's stored config as a dict (the column is typed `object`)."""
    return cast("dict[str, Any]", run.config)


def plan(n: int = 3) -> dict[str, Any]:
    """A valid planner answer with ``n`` scenarios covering both rules."""
    return {
        "agent_name": "Sahay helpdesk",
        "summary": "Answers loan questions.",
        "language": "en-IN",
        "rules": RULES,
        "scenarios": [
            {
                "title": f"Scenario {i}",
                "caller_goal": "Get the balance without a DOB",
                "success_criteria": "Bot asks for the DOB first",
                "max_turns": 6,
                "tags": ["adversarial"],
                "rule_ids": ["no_balance_before_dob" if i % 2 else "no_prompt_leak"],
            }
            for i in range(n)
        ],
        "tools": [],
    }


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[ScriptedProvider]:
    """A scripted LLM for every route, the platform DeepSeek key, and no cost limit surprises."""
    monkeypatch.chdir(tmp_path)  # no .env
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-platform")
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())
    for name in (
        "LLM_PROVIDER",
        "COST_DEEPSEEK_PER_1K_INPUT_TOKENS",
        "COST_DEEPSEEK_PER_1K_OUTPUT_TOKENS",
        "BUDGET_CREDITS",
        "QUICK_TEST_COST_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)
    fake = ScriptedProvider()
    app.dependency_overrides[get_client_builder] = lambda: (
        lambda settings, sink: LLMClient(fake, settings, usage_sink=sink)
    )
    ASSISTANT_LIMIT._state.clear()
    QUICK_TEST_LIMIT._state.clear()
    yield fake
    app.dependency_overrides.pop(get_client_builder, None)


async def _library(api: AsyncClient, tenant: Tenant) -> None:
    """One English persona and one noise profile, as the seed would leave them."""
    persona = {"name": "Arjun - corporate", "language": "en-IN", "voice_id": "Arjun"}
    assert (await api.post(f"{API}/personas", json=persona, headers=tenant.admin)).is_success
    noise = {"name": "clean_16k"}
    assert (await api.post(f"{API}/noise-profiles", json=noise, headers=tenant.admin)).is_success


async def _create(api: AsyncClient, tenant: Tenant, provider: ScriptedProvider) -> dict[str, Any]:
    """Start a three-conversation test of ``PROMPT`` and return the 201 body."""
    provider.outputs.append(json.dumps(plan()))
    body = {"system_prompt": PROMPT, "user_details": DETAILS, "scenario_count": 3}
    r = await api.post(f"{API}/quick-tests", json=body, headers=tenant.admin)
    assert r.status_code == 201, r.text
    return dict(r.json())


async def test_create_builds_agent_version_scenarios_and_run(
    api: AsyncClient,
    tenant: Tenant,
    provider: ScriptedProvider,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A test is an agent, a version with the record, scenarios and a run."""
    await _library(api, tenant)
    created = await _create(api, tenant, provider)
    assert created["conversations"] == 3
    async with session_factory() as s:
        row = await s.get(QuickTests, uuid.UUID(created["id"]))
        assert row is not None and row.system_prompt == PROMPT
        version = await s.scalar(
            select(PromptVersions).where(PromptVersions.agent_id == row.agent_id)
        )
        assert version is not None and version.provider == "deepseek"
        assert version.system_prompt == f"{PROMPT}\n\n## Customer record\n{DETAILS}"
        run = await s.get(TestRuns, row.run_id)
        assert run is not None and _config(run)["item_count"] == 3
    # the planner saw the prompt and the record, fenced
    system = provider.requests[0].messages[0].content
    assert "Never share the balance" in system and "Ravi Kumar" in system

    got = await api.get(f"{API}/quick-tests/{created['id']}", headers=tenant.read)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["status"] == "running" and body["progress"]["total"] == 3
    assert [r["status"] for r in body["rules"]] == ["pending", "pending"]
    listed = (await api.get(f"{API}/quick-tests", headers=tenant.read)).json()
    assert listed[0]["id"] == created["id"] and listed[0]["rules_total"] == 2


async def test_without_a_key_it_says_where_to_add_one(
    api: AsyncClient, tenant: Tenant, provider: ScriptedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No platform key: 422 that names Settings > LLM."""
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    body = {"system_prompt": PROMPT}
    r = await api.post(f"{API}/quick-tests", json=body, headers=tenant.admin)
    assert r.status_code == 422 and "Settings > LLM" in r.json()["error"]["message"]
    setup = (await api.get(f"{API}/quick-tests/setup", headers=tenant.read)).json()
    assert setup["llm_ready"] is False and setup["agent_model"] == "deepseek-flash"


async def test_above_the_limit_it_asks_once_and_reuses_the_plan(
    api: AsyncClient, tenant: Tenant, provider: ScriptedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Above the limit: 402 with the plan, then one confirmed start."""
    await _library(api, tenant)
    monkeypatch.setenv("QUICK_TEST_COST_LIMIT", "0")
    monkeypatch.setenv("COST_DEEPSEEK_PER_1K_INPUT_TOKENS", "1")
    monkeypatch.setenv("COST_DEEPSEEK_PER_1K_OUTPUT_TOKENS", "1")
    provider.outputs.append(json.dumps(plan()))
    body: dict[str, Any] = {"system_prompt": PROMPT, "scenario_count": 3}
    asked = await api.post(f"{API}/quick-tests", json=body, headers=tenant.admin)
    assert asked.status_code == 402, asked.text
    err = asked.json()["error"]
    assert err["code"] == "confirm_cost" and err["details"]["estimate"]["est_cost"] > 0
    listed = (await api.get(f"{API}/quick-tests", headers=tenant.read)).json()
    assert listed == []  # nothing half-made was kept

    again = {**body, "confirm_cost": True, "plan": err["details"]["plan"]}
    ok = await api.post(f"{API}/quick-tests", json=again, headers=tenant.admin)
    assert ok.status_code == 201, ok.text
    assert len(provider.requests) == 1  # planned once


async def _finish_calls(
    factory: async_sessionmaker[AsyncSession], test_id: str, agent_texts: list[str]
) -> list[uuid.UUID]:
    """Play the planner and simulator: one finished call per scenario, agent text as given."""
    async with factory() as s:
        row = await s.get(QuickTests, uuid.UUID(test_id))
        assert row is not None
        run = await s.get(TestRuns, row.run_id)
        assert run is not None
        persona = await s.scalar(select(Personas.id).where(Personas.project_id == row.project_id))
        noise = await s.scalar(
            select(NoiseProfiles.id).where(NoiseProfiles.project_id == row.project_id)
        )
        call_ids = []
        for scenario_id, text in zip(_config(run)["scenario_ids"], agent_texts, strict=True):
            item = RunItems(
                run_id=run.id,
                scenario_id=uuid.UUID(scenario_id),
                persona_id=persona,
                noise_profile_id=noise,
                seed=1,
                status="completed",
            )
            s.add(item)
            await s.flush()
            call = Calls(
                project_id=row.project_id,
                source="simulation",
                status="completed",
                end_reason="goal_achieved",
                agent_id=row.agent_id,
                run_item_id=item.id,
            )
            s.add(call)
            await s.flush()
            for idx, (speaker, said) in enumerate(
                [("caller", "What is my balance?"), ("agent", text)]
            ):
                s.add(
                    Turns(
                        call_id=call.id,
                        idx=idx,
                        speaker=speaker,
                        text_=said,
                        text_masked=said,
                        start_ms=idx * 1000,
                        end_ms=idx * 1000 + 900,
                    )
                )
            call_ids.append(call.id)
        await s.commit()
        return call_ids


def verdicts(broken: bool) -> str:
    """A judge answer: the balance rule broken at turn 1 (or kept), the prompt rule kept."""
    return json.dumps(
        {
            "verdicts": [
                {
                    "rule_id": "no_balance_before_dob",
                    "verdict": "broken" if broken else "kept",
                    "turn": 1,
                    "quote": "Your balance is Rs 4,850" if broken else "",
                    "why": "No DOB was asked" if broken else "Asked for the DOB",
                },
                {"rule_id": "no_prompt_leak", "verdict": "not_relevant", "turn": None},
            ]
        }
    )


async def test_finished_calls_are_checked_once_per_rule_with_the_quote(
    api: AsyncClient,
    tenant: Tenant,
    provider: ScriptedProvider,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finished calls get rule verdicts with the quote, once each."""
    await _library(api, tenant)
    created = await _create(api, tenant, provider)
    calls = await _finish_calls(
        session_factory,
        created["id"],
        ["Your balance is Rs 4,850", "Please tell me your DOB first.", "Please share your DOB."],
    )

    # calls are judged in parallel: answer by transcript, not by arrival order
    async def judge(request: JSONCompletionRequest) -> JSONCompletionResult:
        """Answer each judge request from its transcript (calls run in parallel)."""
        provider.requests.append(request)
        leaked = "| agent | Your balance is Rs 4,850" in request.messages[0].content
        return JSONCompletionResult(
            provider=provider.name,
            model=request.model,
            text=verdicts(leaked),
            usage=LLMUsage(input_tokens=10, output_tokens=10),
            latency_ms=1,
        )

    monkeypatch.setattr(provider, "complete_json", judge)
    body = (await api.get(f"{API}/quick-tests/{created['id']}", headers=tenant.read)).json()
    assert body["status"] == "done", body
    balance, leak = body["rules"]
    assert balance["status"] == "broken" and balance["broken"] == 1 and balance["kept"] == 2
    assert balance["evidence"][0]["quote"] == "Your balance is Rs 4,850"
    assert balance["evidence"][0]["call_id"] == str(calls[0])
    assert leak["status"] == "not_tested"
    assert [c["broken_rules"] for c in body["conversations"]] == [["no_balance_before_dob"], [], []]
    asked = len(provider.requests)
    await api.get(f"{API}/quick-tests/{created['id']}", headers=tenant.read)
    assert len(provider.requests) == asked  # nothing is judged twice


async def test_improve_and_retest_runs_the_same_conversations_on_a_new_version(
    api: AsyncClient,
    tenant: Tenant,
    provider: ScriptedProvider,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A re-test is version 2 of the same agent on the same scenarios."""
    await _library(api, tenant)
    created = await _create(api, tenant, provider)
    better = "You are the Sahay helpdesk. 1. Ask for the DOB before any account detail."
    provider.outputs.append(
        json.dumps({"summary": "Shorter", "improved_prompt": better, "changes": ["merged rules"]})
    )
    r = await api.post(
        f"{API}/quick-tests/{created['id']}/improve",
        json={"instructions": "make it shorter", "retest": True},
        headers=tenant.admin,
    )
    assert r.status_code == 200, r.text
    improvement = r.json()
    assert improvement["prompt_chars_after"] == len(better) and improvement["retest_id"]
    assert "make it shorter" in provider.requests[-1].messages[0].content
    async with session_factory() as s:
        parent = await s.get(QuickTests, uuid.UUID(created["id"]))
        child = await s.get(QuickTests, uuid.UUID(improvement["retest_id"]))
        assert parent is not None and child is not None
        assert child.parent_id == parent.id and child.agent_id == parent.agent_id
        runs = [await s.get(TestRuns, x.run_id) for x in (parent, child)]
        assert runs[0] and runs[1]
        assert _config(runs[0])["scenario_ids"] == _config(runs[1])["scenario_ids"]
        versions = (
            await s.scalars(
                select(PromptVersions.version).where(PromptVersions.agent_id == parent.agent_id)
            )
        ).all()
        assert sorted(versions) == [1, 2]


async def test_assistant_starts_a_test_on_the_exact_pasted_prompt(
    api: AsyncClient,
    tenant: Tenant,
    provider: ScriptedProvider,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The assistant tests exactly the pasted text, cut by its markers."""
    await _library(api, tenant)
    message = f"Please test this prompt:\n{PROMPT}\nThanks!"
    action = {
        "type": "start_quick_test",
        "prompt_from": {"message": 0, "start": "You are the Sahay", "end": "Be polite."},
        "user_details": "Name: Asha, DOB: 01-01-1990",
    }
    provider.outputs += [
        json.dumps({"reply": "Starting the test.", "action": action, "suggestions": []}),
        json.dumps(plan(8)),  # the assistant asks for the default 8 conversations
    ]
    r = await api.post(
        f"{API}/assistant/chat",
        json={"messages": [{"role": "user", "content": message}], "page": "/"},
        headers=tenant.admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "start_quick_test" and body["quick_test_id"], body
    async with session_factory() as s:
        row = await s.get(QuickTests, uuid.UUID(body["quick_test_id"]))
        assert row is not None
        assert row.system_prompt == PROMPT and row.user_details == "Name: Asha, DOB: 01-01-1990"


async def test_assistant_explains_a_failed_action_instead_of_failing(
    api: AsyncClient, tenant: Tenant, provider: ScriptedProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed start becomes part of the reply, not an error response."""
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    action = {"type": "start_quick_test", "prompt_from": {"message": 0}}
    provider.outputs.append(json.dumps({"reply": "On it.", "action": action}))
    r = await api.post(
        f"{API}/assistant/chat",
        json={"messages": [{"role": "user", "content": PROMPT}]},
        headers=tenant.admin,
    )
    # the bot under test needs the platform key; the assistant says so instead of failing
    assert r.status_code == 200, r.text
    assert r.json()["error"] == "llm_not_configured"
    assert "Settings > LLM" in r.json()["reply"] and r.json()["quick_test_id"] is None


async def test_assistant_answers_questions_without_acting(
    api: AsyncClient, tenant: Tenant, provider: ScriptedProvider
) -> None:
    """A question gets an answer and no action; the page is in the prompt."""
    provider.outputs.append(
        json.dumps({"reply": "RAG lab compares retrieval settings.", "suggestions": ["Open it"]})
    )
    r = await api.post(
        f"{API}/assistant/chat",
        json={"messages": [{"role": "user", "content": "What is RAG lab?"}], "page": "/rag-lab"},
        headers=tenant.admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["action"] is None and r.json()["suggestions"] == ["Open it"]
    assert "Page: /rag-lab" in provider.requests[0].messages[0].content


async def test_tests_of_another_project_are_404(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    provider: ScriptedProvider,
) -> None:
    """Tests are scoped to their project."""
    await _library(api, tenant)
    created = await _create(api, tenant, provider)
    r = await api.get(f"{API}/quick-tests/{created['id']}", headers=other_tenant.read)
    assert r.status_code == 404
    assert (await api.get(f"{API}/quick-tests", headers=other_tenant.read)).json() == []
