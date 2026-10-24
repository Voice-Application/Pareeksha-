"""FR-AU-3: the speaker role is assigned, and a user override swaps the turns and re-evaluates."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from pareeksha.db.models import Calls
from pareeksha.evaluation.rubric import RUBRIC_VERSION
from pareeksha.events.schemas import AnyEnvelope, CallCompleted, EvaluationCompleted, make_envelope
from pareeksha.events.runtime import Database
from pareeksha.events.settings import EventSettings
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.storage.blob import LocalBlobStore
from pareeksha.workers import evaluator as evaluator_worker
from tests.conftest import Tenant
from tests.integration.support import BOOTSTRAP
from tests.integration.audit_support import (
    audit_envelope,
    client_for,
    create_agent,
    fetch_rows,
    make_auditor,
    outbox_envelopes,
    role_reply,
    transaction,
    upload,
)
from tests.unit.evaluation.fakes import ScriptedProvider, judge_json

KEEP = {"spk_0": "agent", "spk_1": "caller"}
SWAPPED = {"spk_0": "caller", "spk_1": "agent"}


async def audited(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> tuple[str, AnyEnvelope]:
    """Upload, run the auditor, and return the call id with the ``call.completed`` it produced."""
    response = await upload(api, tenant, await create_agent(api, tenant))
    call_id: str = response.json()["call_id"]
    auditor, _, _ = make_auditor(blobs, llm_replies=[role_reply(KEEP)])
    async with transaction(database_url) as ctx:
        (out,) = await auditor.handle(await audit_envelope(database_url, call_id), ctx)
    return call_id, make_envelope(out.payload, producer="auditor", correlation_id=call_id)


async def judged(env: AnyEnvelope, database_url: str, provider: ScriptedProvider) -> list[Any]:
    """Run the canonical (EVAL-03b) ``evaluator`` handler with a scripted judge, usage rows on."""
    usage = ApiUsageSink(EventSettings(BOOTSTRAP, database_url))
    evaluator_worker.set_client(
        client_for(provider, usage), usage, Database(EventSettings(BOOTSTRAP, database_url))
    )
    try:
        async with transaction(database_url) as ctx:
            return list(await evaluator_worker.on_call_completed(env, ctx))  # type: ignore[arg-type]
    finally:
        await usage.close()
        evaluator_worker.set_client(None)


async def evaluation_rows(database_url: str, call_id: str) -> list[dict[str, Any]]:
    return await fetch_rows(
        database_url,
        "SELECT e.*, rv.version FROM evaluations e JOIN rubric_versions rv "
        "ON rv.id = e.rubric_version_id WHERE e.call_id = %s",
        call_id,
    )


pytestmark = pytest.mark.usefixtures("rubric")


async def test_swap_rebuilds_turns_and_re_evaluates(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, completed = await audited(api, tenant, blobs, database_url)

    # first judgement: agent = first speaker, who reads the recording disclosure
    first = ScriptedProvider([judge_json(evidence=[0])])
    out = await judged(completed, database_url, first)
    done = out[0].payload
    assert isinstance(done, EvaluationCompleted) and done.passed is True
    (row,) = await evaluation_rows(database_url, call_id)
    assert row["version"] == RUBRIC_VERSION and row["overall_score"] == 100
    checks = await fetch_rows(
        database_url,
        "SELECT check_key, passed FROM deterministic_checks WHERE call_id = %s",
        call_id,
    )
    assert {c["check_key"]: c["passed"] for c in checks}["recording"] is True
    first_prompt = first.requests[0].messages[0].content
    assert (
        "0 | agent |" in first_prompt
        and "this call is recorded" in first_prompt.split("\n0 | agent")[1]
    )

    # the user says the roles are the other way round
    response = await api.post(
        f"/api/v1/calls/{call_id}/speaker-map", json=SWAPPED, headers=tenant.admin
    )
    assert response.status_code == 202 and response.json() == {"call_id": call_id}

    turns = await fetch_rows(
        database_url, "SELECT idx, speaker FROM turns WHERE call_id = %s ORDER BY idx", call_id
    )
    assert [(t["idx"], t["speaker"]) for t in turns] == [(0, "caller"), (1, "agent"), (2, "caller")]
    (call,) = await fetch_rows(database_url, "SELECT * FROM calls WHERE id = %s", call_id)
    assert call["speaker_map"] == SWAPPED and call["status"] == "completed"
    override = call["event_log"][-1]
    assert override["event"] == "speaker_map_override"
    assert override["previous"] == KEEP and override["roles"] == SWAPPED

    # a new call.completed was queued through the outbox, with its own event id
    queued = await outbox_envelopes(database_url, call_id, "pareeksha.call.completed.v1")
    assert len(queued) == 1 and queued[0].event_id != completed.event_id
    payload = queued[0].payload
    assert isinstance(payload, CallCompleted)
    assert payload.source == "upload" and payload.end_reason == "upload" and payload.run_id is None

    # the evaluator judges it again; the evaluation row is replaced, not duplicated
    second = ScriptedProvider([judge_json((2, 2, 2, 2, 2, 2, 2), evidence=[1])])
    out = await judged(queued[0], database_url, second)
    (row2,) = await evaluation_rows(database_url, call_id)
    assert row2["id"] == row["id"] and row2["version"] == RUBRIC_VERSION
    assert row2["overall_score"] == 50
    assert row2["prompt_hash"] == row["prompt_hash"]  # same judge prompt, different transcript
    second_prompt = second.requests[0].messages[0].content
    assert "0 | caller |" in second_prompt and second_prompt != first_prompt
    # the recording disclosure is now missing from the agent's turns: checks were re-run
    checks = await fetch_rows(
        database_url,
        "SELECT check_key, passed FROM deterministic_checks WHERE call_id = %s",
        call_id,
    )
    assert {c["check_key"]: c["passed"] for c in checks}["recording"] is False
    redone = out[0].payload
    assert isinstance(redone, EvaluationCompleted)
    assert redone.needs_human_review is True and "missing_disclosure" in redone.failure_types


async def test_partial_override_keeps_the_other_speakers_role(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, _ = await audited(api, tenant, blobs, database_url)
    both = await api.post(
        f"/api/v1/calls/{call_id}/speaker-map", json={"spk_0": "caller"}, headers=tenant.admin
    )
    assert both.status_code == 400  # spk_1 stays "caller": a call needs an agent too
    ok = await api.post(
        f"/api/v1/calls/{call_id}/speaker-map",
        json={"spk_0": "caller", "spk_1": "agent"},
        headers=tenant.admin,
    )
    assert ok.status_code == 202


async def test_override_validation_and_scoping(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    blobs: LocalBlobStore,
    database_url: str,
    session_factory: Any,
) -> None:
    call_id, _ = await audited(api, tenant, blobs, database_url)
    url = f"/api/v1/calls/{call_id}/speaker-map"

    unknown = await api.post(url, json={"spk_9": "agent"}, headers=tenant.admin)
    assert unknown.status_code == 400
    assert unknown.json()["error"]["details"]["unknown"] == ["spk_9"]
    both_agents = await api.post(
        url, json={"spk_0": "agent", "spk_1": "agent"}, headers=tenant.admin
    )
    assert both_agents.status_code == 400
    bad_role = await api.post(url, json={"spk_0": "manager"}, headers=tenant.admin)
    assert bad_role.status_code == 400

    assert (await api.post(url, json=SWAPPED, headers=other_tenant.admin)).status_code == 404
    assert (await api.post(url, json=SWAPPED, headers=tenant.read)).status_code == 403
    assert (await api.post(url, json=SWAPPED, headers={})).status_code == 401
    missing = await api.post(
        f"/api/v1/calls/{uuid.uuid4()}/speaker-map", json=SWAPPED, headers=tenant.admin
    )
    assert missing.status_code == 404

    # nothing above changed the call
    (call,) = await fetch_rows(database_url, "SELECT speaker_map FROM calls WHERE id = %s", call_id)
    assert call["speaker_map"] == KEEP
    assert await outbox_envelopes(database_url, call_id, "pareeksha.call.completed.v1") == []

    # a simulated call has no diarization to override
    agent_id = await create_agent(api, tenant)
    sim_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            Calls(
                id=sim_id,
                project_id=tenant.project_id,
                agent_id=uuid.UUID(agent_id),
                source="simulation",
                status="completed",
            )
        )
        await session.commit()
    sim = await api.post(f"/api/v1/calls/{sim_id}/speaker-map", json=SWAPPED, headers=tenant.admin)
    assert sim.status_code == 409


async def test_call_still_transcribing_or_without_transcript_cannot_be_remapped(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    response = await upload(api, tenant, await create_agent(api, tenant))
    pending = response.json()["call_id"]  # the auditor has not run
    early = await api.post(
        f"/api/v1/calls/{pending}/speaker-map", json=SWAPPED, headers=tenant.admin
    )
    assert early.status_code == 409 and "transcribing" in early.json()["error"]["message"]

    call_id, _ = await audited(api, tenant, blobs, database_url)
    (blobs.root / f"uploads/{call_id}/stt.json").unlink()
    lost = await api.post(
        f"/api/v1/calls/{call_id}/speaker-map", json=SWAPPED, headers=tenant.admin
    )
    assert lost.status_code == 409


async def test_stored_segments_keep_the_vendor_labels(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, _ = await audited(api, tenant, blobs, database_url)
    stored = json.loads(await blobs.get(f"uploads/{call_id}/stt.json"))
    assert stored["provider"] == "gnani" and stored["language"] == "kn-IN"
    assert [(s["label"], s["raw_speaker"]) for s in stored["segments"]] == [
        ("spk_0", "1"),
        ("spk_0", "1"),
        ("spk_1", "2"),
        ("spk_0", "1"),
    ]
