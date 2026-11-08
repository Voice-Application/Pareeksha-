"""A RAG matrix on any prompt version, active or not: every run pins it and executes it."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.agent_llm.base import AgentMessage, ChatReply, ToolSpec
from pareeksha.events.runtime import Database
from pareeksha.events.schemas import CallCompleted, CallRequested, make_envelope
from pareeksha.runs import service
from pareeksha.schemas.runs import RunConfig, RunCreate
from pareeksha.simulation import store
from pareeksha.workers import simulator
from tests.conftest import Tenant
from tests.integration.audit_support import fetch_rows, transaction
from tests.integration.runs_support import API, plan_in_db
from tests.integration.test_rag_matrix_api import MATRICES, Setup, add_index, env, setup  # noqa: F401
from tests.integration.test_rag_runs import workers  # noqa: F401  (fixture)
from tests.unit.simulation.simfakes import ScriptedCaller
from tests.unit.simulation.test_text_runner import FakeChat, text


async def _new_version(
    api: AsyncClient, tenant: Tenant, s: Setup, prompt: str, **fields: Any
) -> dict[str, Any]:
    """Push a new prompt version (it becomes the active one) and return it."""
    r = await api.post(
        f"{API}/agents/{s.agent_id}/prompt-versions",
        json={"system_prompt": prompt, "provider": "openai", "model": "m2", **fields},
        headers=tenant.admin,
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _version_ids(api: AsyncClient, tenant: Tenant, s: Setup) -> dict[int, str]:
    """``{version number: id}`` of the agent's versions."""
    r = await api.get(f"{API}/agents/{s.agent_id}/prompt-versions", headers=tenant.read)
    assert r.status_code == 200, r.text
    return {v["version"]: v["id"] for v in r.json()}


async def _active_id(s: Setup) -> str | None:
    """The agent's live ``active_version_id``."""
    (row,) = await fetch_rows(s.url, "SELECT adapter_config FROM agents WHERE id = %s", s.agent_id)
    value = row["adapter_config"].get("active_version_id")
    return None if value is None else str(value)


async def _snapshot_versions(s: Setup, matrix: dict[str, Any]) -> list[str]:
    """``agent_snapshot.adapter_config.active_version_id`` of every run of ``matrix``."""
    out: list[str] = []
    for e in matrix["entries"]:
        (row,) = await fetch_rows(
            s.url, "SELECT agent_snapshot FROM test_runs WHERE id = %s", e["run_id"]
        )
        out.append(row["agent_snapshot"]["adapter_config"]["active_version_id"])
    return out


async def _matrix_version_id(s: Setup, matrix_id: str) -> str:
    """``rag_matrices.prompt_version_id`` as text."""
    (row,) = await fetch_rows(
        s.url, "SELECT prompt_version_id::text AS v FROM rag_matrices WHERE id = %s", matrix_id
    )
    return str(row["v"])


async def test_matrix_on_a_non_active_version_pins_every_run(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    """v2 is active; a matrix on v1 is accepted, every run and the row pin v1, v2 stays active."""
    s = await setup(api, tenant, database_url)
    await _new_version(api, tenant, s, "V2 prompt {{context}}")
    ids = await _version_ids(api, tenant, s)
    assert await _active_id(s) == ids[2]
    a = s.cfg(label="bm25")
    await add_index(s, a, 1)

    r = await api.post(MATRICES, json=s.body([a], prompt_version=1), headers=tenant.admin)
    assert r.status_code == 201, r.text
    m = r.json()
    assert len(m["entries"]) == 3
    assert await _snapshot_versions(s, m) == [ids[1]] * 3
    assert await _matrix_version_id(s, m["id"]) == ids[1]
    assert await _active_id(s) == ids[2]  # the matrix did not activate v1
    runs = [e["run_id"] for e in m["entries"]]
    cmp = await api.get(
        f"{API}/runs/compare", params={"base": runs[0], "head": runs[2]}, headers=tenant.read
    )
    assert cmp.status_code == 200, cmp.text
    assert (cmp.json()["base_prompt_version"], cmp.json()["head_prompt_version"]) == (1, 1)


class _ModelChat(FakeChat):
    """``FakeChat`` that also records the model name of every request."""

    def __init__(self, script: Sequence[ChatReply | Exception]) -> None:
        """Script the replies; ``models`` collects the ``model`` argument per request."""
        super().__init__(script)
        self.models: list[str] = []

    async def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        model: str,
        temperature: float,
        timeout_s: float = 60.0,
    ) -> ChatReply:
        """Record ``model``, then behave like ``FakeChat.chat``."""
        self.models.append(model)
        return await super().chat(
            messages, tools, model=model, temperature=temperature, timeout_s=timeout_s
        )


async def test_the_pinned_version_is_what_the_simulator_executes(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    workers: Database,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """read_spec loads v1 for a matrix pinned to v1, and the agent call uses v1's prompt/model."""
    s = await setup(api, tenant, database_url)
    await _new_version(api, tenant, s, "V2 prompt {{context}}", provider="gemini")
    a = s.cfg(label="bm25")
    await add_index(s, a, 1)
    m = (await api.post(MATRICES, json=s.body([a], prompt_version=1), headers=tenant.admin)).json()
    run_id = next(e["run_id"] for e in m["entries"] if e["kind"] == "no_rag")
    (req,) = [
        o.payload
        for o in await plan_in_db(database_url, run_id)
        if isinstance(o.payload, CallRequested)
    ]

    async with transaction(database_url) as ctx:
        spec, _ = await store.read_spec(ctx.tx, req)
    pv = spec.agent.adapter_config["prompt_version"]
    assert (pv["version"], pv["model"], pv["provider"]) == (1, "m", "openai")
    assert pv["system_prompt"] == "Answer using:\n{{context}}"

    chat = _ModelChat([text("Refunds take seven days.")])
    providers: list[str] = []

    def build(provider: str, **_: Any) -> _ModelChat:
        """Record which provider the simulator builds the agent's chat client for."""
        providers.append(provider)
        return chat

    monkeypatch.setattr(simulator, "build_chat_provider", build)
    monkeypatch.setattr(simulator, "_caller", ScriptedCaller(["How long do refunds take?"]))
    env_ = make_envelope(req, producer="planner", correlation_id=run_id)
    async with transaction(database_url) as ctx:
        (out,) = await simulator.on_call_requested(env_, ctx)
    assert isinstance(out.payload, CallCompleted)
    assert providers == ["openai"] and chat.models == ["m"]
    system = chat.seen[0][0].content
    assert system.startswith("Answer using:") and "V2" not in system


async def test_unknown_version_404_writes_nothing(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    """A version number the agent does not have is 404 not_found with the number."""
    s = await setup(api, tenant, database_url)
    a = s.cfg()
    await add_index(s, a, 1)
    r = await api.post(MATRICES, json=s.body([a], prompt_version=9), headers=tenant.admin)
    assert r.status_code == 404, r.text
    err = r.json()["error"]
    assert err["code"] == "not_found" and err["details"] == {"version": 9}
    runs = await api.get(f"{API}/runs", params={"agent_id": s.agent_id}, headers=tenant.read)
    assert runs.json()["items"] == []
    assert (await api.get(MATRICES, headers=tenant.read)).json()["items"] == []


@pytest.mark.parametrize("explicit", [False, True], ids=["default", "explicit-active"])
async def test_active_version_behaviour_unchanged(
    api: AsyncClient, tenant: Tenant, database_url: str, explicit: bool
) -> None:
    """No prompt_version (or the active one's number) pins the active version, as before."""
    s = await setup(api, tenant, database_url)
    await _new_version(api, tenant, s, "V2 prompt {{context}}")
    ids = await _version_ids(api, tenant, s)
    a = s.cfg()
    await add_index(s, a, 1)
    extra = {"prompt_version": 2} if explicit else {}
    r = await api.post(MATRICES, json=s.body([a], **extra), headers=tenant.admin)
    assert r.status_code == 201, r.text
    assert await _snapshot_versions(s, r.json()) == [ids[2]] * 3
    assert await _matrix_version_id(s, r.json()["id"]) == ids[2]
    assert await _active_id(s) == ids[2]


async def test_pin_rag_uses_the_pinned_version(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``_pin_rag`` reads the pinned version's rag_config, not the active version's."""
    s = await setup(api, tenant, database_url, chars=1234)
    fc = {"mode": "full_context", "kb_id": s.kb_id}
    await _new_version(api, tenant, s, "v2 full context {{context}}", rag_config=fc)
    await _new_version(api, tenant, s, "v3 no rag")  # active, no RAG
    ids = await _version_ids(api, tenant, s)
    body = RunCreate(
        agent_id=uuid.UUID(s.agent_id),
        name="pinned",
        scenario_ids=[uuid.UUID(s.scenario_id)],
        persona_ids=[uuid.UUID(s.persona_id)],
        noise_profile_ids=[uuid.UUID(s.noise_id)],
        config=RunConfig(),
    )
    async with session_factory() as session:
        pinned = await service.prepare(session, s.project_id, body, prompt_version=2)
        assert pinned.version is not None and str(pinned.version.id) == ids[2]
        assert await service._pin_rag(session, s.project_id, pinned) == {
            "rag_full_context_chars": 1234
        }
        active = await service.prepare(session, s.project_id, body)
        assert active.version is not None and str(active.version.id) == ids[3]
        assert await service._pin_rag(session, s.project_id, active) == {}
        await session.rollback()
