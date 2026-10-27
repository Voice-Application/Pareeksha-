"""Postgres side of a simulated call: read what ``call.requested`` points at, save the result.

The simulator worker keeps two kinds of connection: ``read_spec`` runs on its own autocommit
connection (so a ~minute-long call never holds a transaction open while it talks to the agent),
``save_call`` runs in the consumer transaction so the call, its turns, the item status and the
slot release commit together with the framework's ``processed_events`` row.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pareeksha.adapters.base import AgentTarget
from pareeksha.audio.profiles import LineProfile
from pareeksha.evaluation.pii import mask_pii
from pareeksha.events.schemas import CallRequested
from pareeksha.runs.slots import release_slot
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate
from pareeksha.simulation.models import CallResult, CallSpec

Conn = psycopg.AsyncConnection[Any]

#: Call ids are derived from the run item so a redelivered request reuses (never duplicates) them.
CALL_NAMESPACE = uuid.UUID("6f0b1c7e-5a43-4a58-9c0e-7a7f3d8f2a11")


def call_id_for(run_item_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(CALL_NAMESPACE, str(run_item_id))


class SpecNotFoundError(LookupError):
    """The request names an agent, scenario, persona or noise profile that does not exist."""


async def read_spec(conn: Conn, req: CallRequested) -> tuple[CallSpec, uuid.UUID]:
    """Build the :class:`CallSpec` for ``req``; also returns the project id."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT project_id, adapter, endpoint_url, adapter_config, languages, glass_box, "
            "max_call_seconds FROM agents WHERE id = %s",
            (req.agent_id,),
        )
        agent = await cur.fetchone()
        await cur.execute(
            "SELECT agent_id, title, caller_goal, fixtures, reveal_rules, success_criteria, "
            "must_say, must_not_say, expected_tool_calls, caller_speaks_first, max_turns, tags "
            "FROM scenarios WHERE id = %s",
            (req.scenario_id,),
        )
        scenario = await cur.fetchone()
        await cur.execute(
            "SELECT name, language, code_mix_style, dialect_label, tts_model, voice_id, "
            "speed::float AS speed, emotion, patience_turns, interruption_level, silence_habit, "
            "behaviour_notes FROM personas WHERE id = %s",
            (req.persona_id,),
        )
        persona = await cur.fetchone()
        await cur.execute(
            "SELECT name, sample_rate, codec, pstn_bandpass, background_category, "
            "snr_db::float AS snr_db, packet_loss_pct::float AS packet_loss_pct, clipping "
            "FROM noise_profiles WHERE id = %s",
            (req.noise_profile_id,),
        )
        noise = await cur.fetchone()
    missing = [
        name
        for name, row in (
            ("agent", agent),
            ("scenario", scenario),
            ("persona", persona),
            ("noise profile", noise),
        )
        if row is None
    ]
    if missing or agent is None or scenario is None or persona is None or noise is None:
        raise SpecNotFoundError(f"call.requested names unknown {', '.join(missing)}")

    config = dict(agent["adapter_config"] or {})
    spec = CallSpec(
        call_id=call_id_for(req.run_item_id),
        agent=AgentTarget(
            agent_id=req.agent_id,
            adapter=agent["adapter"],
            endpoint_url=agent["endpoint_url"],
            adapter_config=config,
            languages=list(agent["languages"] or []),
            glass_box=agent["glass_box"],
        ),
        persona=PersonaCreate(**persona),
        scenario=ScenarioCreate(**{k: v for k, v in scenario.items() if k != "agent_id"}),
        profile=LineProfile(
            name=noise["name"],
            sample_rate=noise["sample_rate"],
            codec=noise["codec"],
            pstn_bandpass=noise["pstn_bandpass"],
            background=noise["background_category"],
            snr_db=noise["snr_db"],
            packet_loss_pct=noise["packet_loss_pct"],
            clipping=noise["clipping"],
        ),
        seed=req.seed,
        max_call_seconds=int(agent["max_call_seconds"]),
        # e.g. {"start_metadata": {"mock_bugs": ["false_waiver"]}} on the agent row
        metadata=dict(config.get("start_metadata") or {}),
    )
    return spec, agent["project_id"]


async def mark_in_progress(conn: Conn, run_item_id: uuid.UUID) -> None:
    await conn.execute(
        "UPDATE run_items SET status = 'in_progress' WHERE id = %s AND status = 'connecting'",
        (run_item_id,),
    )


async def fail_item(conn: Conn, run_id: uuid.UUID, run_item_id: uuid.UUID, message: str) -> None:
    """Give up on an item that cannot be simulated: ``error`` + the slot it took, atomically."""
    async with conn.transaction():
        await conn.execute(
            "UPDATE run_items SET status = 'error', last_error = %s "
            "WHERE id = %s AND status IN ('connecting', 'in_progress')",
            (message[:500], run_item_id),
        )
        await release_slot(conn, run_id)


async def open_call(
    conn: Conn, *, req: CallRequested, project_id: uuid.UUID, spec: CallSpec
) -> None:
    """Create the call row (``in_progress``) before the call starts.

    ``api_usage`` rows written during the call (the caller brain's LLM usage) reference it. A
    redelivery after a crash reuses the same row (the id is derived from the run item).
    """
    await conn.execute(
        "INSERT INTO calls (id, project_id, source, status, agent_id, run_item_id, language, "
        "metadata) VALUES (%s, %s, 'simulation', 'in_progress', %s, %s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        (
            spec.call_id,
            project_id,
            req.agent_id,
            req.run_item_id,
            spec.language,
            Jsonb(
                {
                    "run_id": str(req.run_id),
                    "scenario_id": str(req.scenario_id),
                    "persona_id": str(req.persona_id),
                    "noise_profile_id": str(req.noise_profile_id),
                    "seed": req.seed,
                }
            ),
        ),
    )


def blob_prefix(call_id: uuid.UUID) -> str:
    return f"calls/{call_id}"


async def save_call(
    tx: Conn,
    *,
    req: CallRequested,
    project_id: uuid.UUID,
    spec: CallSpec,
    result: CallResult,
    recording_keys: dict[str, str] | None,
) -> None:
    """Write the finished call, its turns, tool calls and usage; finish the item; free the slot."""
    call_id = spec.call_id
    status = "error" if result.end_reason in ("infra_error", "connect_failed") else "completed"
    await tx.execute(
        "UPDATE calls SET status = %s, metadata = metadata || %s, event_log = %s, "
        "end_reason = %s, duration_ms = %s, recording_caller = %s, recording_agent = %s, "
        "recording_mixed = %s, error = %s, ended_at = now() WHERE id = %s",
        (
            status,
            Jsonb(
                {
                    "glass_box": result.glass_box,
                    "barge_in_attempts": [
                        b.model_dump(mode="json") for b in result.barge_in_attempts
                    ],
                }
            ),
            Jsonb([e.model_dump(mode="json") for e in result.events]),
            result.end_reason,
            result.duration_ms,
            (recording_keys or {}).get("caller"),
            (recording_keys or {}).get("agent"),
            (recording_keys or {}).get("mixed"),
            result.error,
            call_id,
        ),
    )
    async with tx.cursor() as cur:
        await cur.executemany(
            "INSERT INTO turns (call_id, idx, speaker, text, text_masked, start_ms, end_ms, "
            "is_barge_in, ground_truth_text, agent_heard_text, language_detected, stt_confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (call_id, idx) DO NOTHING",
            [
                (
                    call_id,
                    t.idx,
                    t.speaker,
                    t.text,
                    mask_pii(t.text),
                    t.start_ms,
                    t.end_ms,
                    t.is_barge_in,
                    t.ground_truth_text or (t.glass_box_text if t.speaker == "agent" else t.text),
                    t.agent_heard_text,
                    t.language_detected,
                    t.stt_confidence,
                )
                for t in result.turns
            ],
        )
        await cur.executemany(
            "INSERT INTO tool_calls (call_id, seq, name, arguments, at_ms, turn_idx, result) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (call_id, seq) DO NOTHING",
            [
                (call_id, c.seq, c.name, Jsonb(c.arguments), c.at_ms, c.turn_idx, Jsonb(c.result))
                for c in result.tool_calls
            ],
        )
        await cur.executemany(
            "INSERT INTO api_usage (provider, operation, units, unit_type, est_cost, cached, "
            "run_id, call_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    u.provider,
                    u.operation,
                    u.audio_seconds if u.kind == "stt" else u.characters,
                    "audio_seconds" if u.kind == "stt" else "characters",
                    u.est_cost,
                    u.cached,
                    req.run_id,
                    call_id,
                )
                # LLM usage is written by the caller brain's own usage sink
                for u in result.usage
                if u.kind in ("stt", "tts")
            ],
        )
    await tx.execute(
        "UPDATE run_items SET status = %s, last_error = %s "
        "WHERE id = %s AND status IN ('connecting', 'in_progress')",
        ("error" if status == "error" else "completed", result.error, req.run_item_id),
    )
    await release_slot(tx, req.run_id)
