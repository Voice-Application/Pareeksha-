"""The ``auditor`` and ``evaluator`` consumers are registered with the INFRA-02 framework."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from pareeksha.evaluation.pg_stores import PgEvaluatorStore
from pareeksha.events.consumer import REGISTRY
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.llm.client import LLMClient
from pareeksha.speech.providers.gnani import GnaniSTT
from pareeksha.storage.blob import LocalBlobStore
from pareeksha.workers import auditor as auditor_worker
from pareeksha.workers import evaluator as evaluator_worker
from tests.conftest import Tenant
from tests.integration.audit_support import (
    audit_envelope,
    client_for,
    create_agent,
    tone_wav,
    transaction,
    upload,
)
from tests.integration.test_agent_role_swap import audited
from tests.integration.support import BOOTSTRAP
from tests.unit.evaluation.fakes import ScriptedProvider, judge_json


def test_both_consumers_are_registered_on_their_topics() -> None:
    audit = REGISTRY["auditor"]
    assert audit.topics == (Topics.AUDIT_REQUESTED,) and audit.reproduce is not None
    assert audit.max_poll_interval_ms >= 600_000  # a batch STT job outlives the 5 min default
    evaluator = REGISTRY["evaluator"]
    assert evaluator.topics == (Topics.CALL_COMPLETED,) and evaluator.reproduce is not None


def test_auditor_dependencies_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("GNANI_API_KEY", "DEEPSEEK_API_KEY", "LLM_PROVIDER", "STT_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # no .env here
    assert auditor_worker._llm_or_none() is None  # no key: role check degrades to the heuristic

    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("GNANI_API_KEY", "g")
    client = auditor_worker._llm_or_none()
    assert isinstance(client, LLMClient)
    auditor_worker.get_auditor.cache_clear()
    try:
        auditor = auditor_worker.get_auditor()
        assert auditor.deps.llm is not None
        assert isinstance(auditor.deps.stt_factory(), GnaniSTT)
        assert auditor_worker.get_auditor() is auditor  # built once per process
    finally:
        auditor_worker.get_auditor.cache_clear()


async def test_registered_auditor_handler_runs_the_pipeline(
    api: AsyncClient,
    tenant: Tenant,
    blobs: LocalBlobStore,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.integration.audit_support import make_auditor

    response = await upload(api, tenant, await create_agent(api, tenant), audio=tone_wav())
    call_id = response.json()["call_id"]
    env = await audit_envelope(database_url, call_id)
    fake, _, _ = make_auditor(blobs, llm_replies=None)
    monkeypatch.setattr(auditor_worker, "get_auditor", lambda: fake)
    async with transaction(database_url) as ctx:
        (out,) = await auditor_worker.handle_audit_requested(env, ctx)
    async with transaction(database_url) as ctx:
        again = await auditor_worker._reproduce(env, ctx)
    assert out.payload == again[0].payload and str(out.payload.call_id) == call_id  # type: ignore[attr-defined]


@pytest.mark.usefixtures("rubric")
async def test_registered_evaluator_handler_judges_the_call(
    api: AsyncClient,
    tenant: Tenant,
    blobs: LocalBlobStore,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pareeksha.events.schemas import make_envelope

    call_id, completed = await audited(api, tenant, blobs, database_url)
    provider = ScriptedProvider([judge_json(evidence=[0])])
    usage = ApiUsageSink(EventSettings(BOOTSTRAP, database_url))
    monkeypatch.setattr(evaluator_worker, "get_client", lambda: (client_for(provider, usage), usage))
    env = make_envelope(completed.payload, producer="auditor", correlation_id=call_id)
    async with transaction(database_url) as ctx:
        out = await evaluator_worker.on_call_completed(env, ctx)
    assert [o.payload.event_type.value for o in out] == ["evaluation.completed", "progress"]


@pytest.mark.usefixtures("rubric")
async def test_uploads_have_no_tool_trace_even_for_a_glass_box_agent(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    agent_id = await create_agent(api, tenant, glass_box=True)
    call_id = (await upload(api, tenant, agent_id)).json()["call_id"]
    async with transaction(database_url) as ctx:
        snapshot = await PgEvaluatorStore(ctx.tx).load_snapshot(uuid.UUID(call_id))
    assert snapshot is not None and snapshot.tool_calls is None  # unknown, not "no tools called"
    assert snapshot.scenario is None and snapshot.persona is None
