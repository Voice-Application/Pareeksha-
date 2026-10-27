"""FR-AU-4: an audit is judged with the same rubric version and judge prompt as a simulation.

Also covers the Postgres evaluator store (EVAL-04 wires the ``evaluator`` consumer to it).
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from pareeksha.evaluation.evaluator import evaluate_call
from pareeksha.evaluation.pg_stores import PgEvaluatorStore, RubricNotFoundError
from pareeksha.evaluation.rubric import RUBRIC_VERSION
from pareeksha.events.consumer import PermanentError
from pareeksha.events.schemas import (
    CallCompleted,
    EvaluationCompleted,
    ProgressEvent,
    make_envelope,
)
from pareeksha.llm.prompts import prompt_hash
from pareeksha.storage.blob import LocalBlobStore
from pareeksha.workers.evaluator import reproduce
from tests.conftest import Tenant
from tests.integration.audit_support import fetch_rows, transaction
from tests.integration.test_agent_role_swap import audited, judged
from tests.unit.evaluation.fakes import ScriptedProvider, client_for, judge_json

pytestmark = pytest.mark.usefixtures("rubric")


async def make_simulation(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> tuple[str, str, str]:
    """A finished simulated call with scenario, persona, tool trace and a run item."""
    agent = await api.post(
        "/api/v1/agents",
        json={
            "name": f"sim-{uuid.uuid4().hex[:6]}",
            "adapter": "audio_v1",
            "endpoint_url": "ws://mock-agent:8765/ws",
            "languages": ["hi-IN", "en-IN"],
            "glass_box": True,
            "mandatory_disclosures": [{"id": "recording", "text": "recorded", "regex": "record"}],
        },
        headers=tenant.admin,
    )
    agent_id = agent.json()["id"]
    async with transaction(database_url) as ctx:
        tx = ctx.tx

        async def one(sql: str, *args: Any) -> Any:
            cur = await tx.execute(sql, args)
            return (await cur.fetchone())[0]  # type: ignore[index]

        scenario = await one(
            "INSERT INTO scenarios (project_id, agent_id, title, caller_goal, success_criteria, "
            "fixtures, expected_tool_calls) VALUES (%s, %s, 's', 'pay EMI', 'ptp recorded', "
            '\'{"emi_amount": 4200, "name": "Asha"}\', '
            '\'[{"name": "record_ptp", "args": {"amount": 4200}}]\') RETURNING id',
            tenant.project_id,
            agent_id,
        )
        persona = await one(
            "INSERT INTO personas (project_id, name, language, voice_id) "
            "VALUES (%s, 'Rohit', 'hi-IN', 'Shubham') RETURNING id",
            tenant.project_id,
        )
        noise = await one(
            "INSERT INTO noise_profiles (project_id, name) VALUES (%s, 'clean') RETURNING id",
            tenant.project_id,
        )
        run = await one(
            "INSERT INTO test_runs (project_id, agent_id, status) VALUES (%s, %s, 'running') "
            "RETURNING id",
            tenant.project_id,
            agent_id,
        )
        item = await one(
            "INSERT INTO run_items (run_id, scenario_id, persona_id, noise_profile_id, seed, "
            "status) VALUES (%s, %s, %s, %s, 1, 'completed') RETURNING id",
            run,
            scenario,
            persona,
            noise,
        )
        call = await one(
            "INSERT INTO calls (project_id, agent_id, run_item_id, source, language, status) "
            "VALUES (%s, %s, %s, 'simulation', 'hi-IN', 'completed') RETURNING id",
            tenant.project_id,
            agent_id,
            item,
        )
        turns = [
            (0, "agent", "Namaste, this call is recorded. Your EMI is 4200 rupees.", None),
            (1, "caller", "ठीक है, मैं शुक्रवार को चार हज़ार दो सौ दूँगा", "Theek hai"),
            (2, "agent", "Noted, thank you.", None),
        ]
        for idx, speaker, text, said in turns:
            await tx.execute(
                "INSERT INTO turns (call_id, idx, speaker, text, text_masked, start_ms, end_ms, "
                "ground_truth_text) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (call, idx, speaker, text, text, idx * 3000, idx * 3000 + 2500, said),
            )
        await tx.execute(
            "INSERT INTO tool_calls (call_id, turn_idx, seq, name, arguments, at_ms) "
            "VALUES (%s, 1, 0, 'record_ptp', '{\"amount\": 4200}', 4000)",
            (call,),
        )
    return str(call), str(item), str(run)


def completed_event(
    call_id: str, source: str = "upload", run: str | None = None, item: str | None = None
) -> Any:
    return make_envelope(
        CallCompleted(
            call_id=uuid.UUID(call_id),
            source=source,  # type: ignore[arg-type]
            run_id=None if run is None else uuid.UUID(run),
            run_item_id=None if item is None else uuid.UUID(item),
        ),
        producer="t",
        correlation_id=call_id,
    )


async def test_upload_and_simulation_use_the_same_rubric_and_judge_prompt(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    upload_id, upload_env = await audited(api, tenant, blobs, database_url)
    sim_id, item_id, run_id = await make_simulation(api, tenant, database_url)

    audit_judge = ScriptedProvider([judge_json(evidence=[0])])
    sim_judge = ScriptedProvider([judge_json(evidence=[0])])
    await judged(upload_env, database_url, audit_judge)
    sim_out = await judged(
        completed_event(sim_id, "simulation", run_id, item_id), database_url, sim_judge
    )

    rows = {
        r["call_id"].hex: r
        for r in await fetch_rows(
            database_url,
            "SELECT e.*, rv.version FROM evaluations e JOIN rubric_versions rv "
            "ON rv.id = e.rubric_version_id WHERE e.call_id = ANY(%s)",
            [uuid.UUID(upload_id), uuid.UUID(sim_id)],
        )
    }
    audit_eval, sim_eval = rows[uuid.UUID(upload_id).hex], rows[uuid.UUID(sim_id).hex]
    assert audit_eval["rubric_version_id"] == sim_eval["rubric_version_id"]
    assert audit_eval["version"] == sim_eval["version"] == RUBRIC_VERSION
    assert audit_eval["prompt_hash"] == sim_eval["prompt_hash"]
    assert audit_eval["prompt_hash"].endswith(prompt_hash("judge_v1"))
    assert audit_eval["judge_model"] == sim_eval["judge_model"]
    assert audit_eval["temperature"] == sim_eval["temperature"] == 0

    # both judge prompts carry the same rubric anchors and output contract
    a, s = (p.requests[0].messages[0].content for p in (audit_judge, sim_judge))
    assert a.split("## Anchors")[1] == s.split("## Anchors")[1]

    # the simulation snapshot has the scenario, persona and tool trace; the upload has none
    assert "Persona" in s or "pay EMI" in s
    assert "pay EMI" not in a and "record_ptp" in s and "not available" in a

    # run bookkeeping: the item is evaluated and the run event carries the run ids
    (item,) = await fetch_rows(database_url, "SELECT status FROM run_items WHERE id = %s", item_id)
    assert item["status"] == "evaluated"
    done = sim_out[0].payload
    assert isinstance(done, EvaluationCompleted) and str(done.run_item_id) == item_id
    assert done.run_id is not None and isinstance(sim_out[1].payload, ProgressEvent)

    metrics = {
        str(m["call_id"]): m
        for m in await fetch_rows(
            database_url,
            "SELECT * FROM call_metrics WHERE call_id = ANY(%s)",
            [uuid.UUID(upload_id), uuid.UUID(sim_id)],
        )
    }
    assert metrics[upload_id]["latency_is_approximate"] is True
    assert metrics[sim_id]["latency_is_approximate"] is False
    assert metrics[upload_id]["turn_count"] == 3 and metrics[sim_id]["turn_count"] == 3

    usage = await fetch_rows(
        database_url,
        "SELECT provider, unit_type, units FROM api_usage "
        "WHERE call_id = %s AND operation = 'llm_judge'",
        uuid.UUID(upload_id),
    )
    assert [(u["provider"], u["unit_type"], u["units"]) for u in usage] == [
        ("deepseek", "tokens", 1200)
    ]


async def test_upload_language_drives_the_language_check(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await audited(api, tenant, blobs, database_url)
    await judged(env, database_url, ScriptedProvider([judge_json(evidence=[0])]))
    checks = await fetch_rows(
        database_url,
        "SELECT check_type FROM deterministic_checks WHERE call_id = %s",
        call_id,
    )
    assert "language_match" in {c["check_type"] for c in checks}  # expected_language = kn-IN


async def test_judge_that_never_validates_is_stored_as_judge_error(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    sim_id, item_id, run_id = await make_simulation(api, tenant, database_url)
    bad = judge_json(evidence=[99])  # cites a turn that does not exist, twice -> judge_error
    out = await judged(
        completed_event(sim_id, "simulation", run_id, item_id),
        database_url,
        ScriptedProvider([bad, bad]),
    )
    (row,) = await fetch_rows(
        database_url, "SELECT status, overall_score FROM evaluations WHERE call_id = %s", sim_id
    )
    assert row == {"status": "judge_error", "overall_score": None}
    (item,) = await fetch_rows(database_url, "SELECT status FROM run_items WHERE id = %s", item_id)
    assert item["status"] == "judge_error" and len(out) == 1


async def test_unknown_rubric_version_is_permanent(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, _ = await audited(api, tenant, blobs, database_url)
    async with transaction(database_url) as ctx:
        store = PgEvaluatorStore(ctx.tx)
        snapshot = await store.load_snapshot(uuid.UUID(call_id))
        assert snapshot is not None
        record = await evaluate_call(
            snapshot, client_for(ScriptedProvider([judge_json(evidence=[0])]))
        )
        with pytest.raises(RubricNotFoundError, match="rubric-0000"):
            await store.save_evaluation(dataclasses.replace(record, rubric_version="rubric-0000"))
        assert await store.load_snapshot(uuid.uuid4()) is None


async def test_duplicate_delivery_reproduces_the_same_events(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await audited(api, tenant, blobs, database_url)
    first = await judged(env, database_url, ScriptedProvider([judge_json(evidence=[0])]))
    async with transaction(database_url) as ctx:
        again = await reproduce(env, ctx)
    assert [type(o.payload) for o in again] == [type(o.payload) for o in first]
    assert again[0].payload == first[0].payload
    assert again[1].payload == first[1].payload
    ghost = completed_event(str(uuid.uuid4()))
    async with transaction(database_url) as ctx:
        assert await reproduce(ghost, ctx) == []
    assert call_id


async def test_evaluating_a_call_that_does_not_exist_is_a_dead_letter(database_url: str) -> None:
    with pytest.raises(PermanentError):  # the worker maps CallNotFoundError to a dead letter
        await judged(completed_event(str(uuid.uuid4())), database_url, ScriptedProvider([]))
