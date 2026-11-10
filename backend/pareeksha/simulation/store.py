"""Postgres side of a simulated call: read what ``call.requested`` points at, save the result.

The simulator worker keeps two kinds of connection: ``read_spec`` runs on its own autocommit
connection (so a ~minute-long call never holds a transaction open while it talks to the agent),
``save_call`` runs in the consumer transaction so the call, its turns, the item status and the
slot release commit together with the framework's ``processed_events`` row.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pareeksha.adapters.base import AgentTarget
from pareeksha.audio.profiles import LineProfile
from pareeksha.evaluation.pii import mask_pii
from pareeksha.events.outbox import enqueue
from pareeksha.events.schemas import CallRequested, ProgressEvent, make_envelope
from pareeksha.integrations.crypto import SecretBox, SecretDecryptError
from pareeksha.rag.retriever import LoadedIndex, build_loaded_index, get_or_load
from pareeksha.runs.slots import ACTIVE_ITEM_STATUSES, release_slot
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.prompts import PromptVersionOut
from pareeksha.schemas.rag import RagConfig, index_key
from pareeksha.schemas.scenarios import ScenarioCreate
from pareeksha.simulation.models import CallResult, CallSpec

Conn = psycopg.AsyncConnection[Any]

#: Call ids are derived from the run item so a redelivered request reuses (never duplicates) them.
CALL_NAMESPACE = uuid.UUID("6f0b1c7e-5a43-4a58-9c0e-7a7f3d8f2a11")


def call_id_for(run_item_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(CALL_NAMESPACE, str(run_item_id))


class SpecNotFoundError(LookupError):
    """The request names an agent, scenario, persona or noise profile that does not exist
    (or the agent's stored secrets cannot be read)."""


async def read_spec(conn: Conn, req: CallRequested) -> tuple[CallSpec, uuid.UUID]:
    """Build the :class:`CallSpec` for ``req``; also returns the project id."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT project_id, adapter, endpoint_url, adapter_config, adapter_secrets_encrypted, "
            "languages, glass_box, max_call_seconds FROM agents WHERE id = %s",
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
        await cur.execute("SELECT agent_snapshot FROM test_runs WHERE id = %s", (req.run_id,))
        run = await cur.fetchone()
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

    snapshot = (run or {}).get("agent_snapshot") or {}
    # the adapter the run was created with: a queued prompt run stays a prompt run even if the
    # agent's adapter is changed later
    adapter = snapshot.get("adapter") or agent["adapter"]
    config = dict(agent["adapter_config"] or {})
    # only a version resolved below is ever run, never one stored in the agent's config
    config.pop("prompt_version", None)
    secrets: dict[str, str] = {}
    if adapter == "prompt":
        pinned = (snapshot.get("adapter_config") or {}).get("active_version_id")
        version = await _prompt_version(
            conn, req, agent["project_id"], pinned or config.get("active_version_id")
        )
        if version is not None:  # absent -> the simulator ends the call connect_failed
            config["prompt_version"] = version.model_dump(mode="json")
        if agent["adapter_secrets_encrypted"]:
            try:
                secrets = _secret_box().decrypt(bytes(agent["adapter_secrets_encrypted"]).decode())
            except (SecretDecryptError, RuntimeError, ValueError) as exc:
                # permanent (wrong/missing SECRET_KEY): fail the item rather than retry forever
                raise SpecNotFoundError("the agent's provider secrets cannot be decrypted") from exc
        if version is not None:
            rag = await _rag_target(conn, req, agent["project_id"], version)
            if rag is not None:
                config["rag"], kb_secrets = rag
                secrets = {**secrets, **kb_secrets}
    spec = CallSpec(
        call_id=call_id_for(req.run_item_id),
        agent=AgentTarget(
            agent_id=req.agent_id,
            adapter=adapter,
            endpoint_url=agent["endpoint_url"],
            adapter_config=config,
            adapter_secrets=secrets,
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


def _secret_box() -> SecretBox:
    """The ``SecretBox`` keyed by ``SECRET_KEY``; raises ``RuntimeError`` when it is unset."""
    key = os.environ.get("SECRET_KEY")
    if not key:
        raise RuntimeError("SECRET_KEY is not configured")
    return SecretBox(key)


async def _prompt_version(
    conn: Conn, req: CallRequested, project_id: uuid.UUID, version_id: Any
) -> PromptVersionOut | None:
    """The version the run pinned in its agent snapshot, else the agent's current active one."""
    if not version_id:
        return None
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, agent_id, version, system_prompt, provider, model, base_url, temperature, "
            "tools, max_tool_rounds, rag_config, note, content_hash, created_at "
            "FROM prompt_versions "
            "WHERE id = %s AND agent_id = %s AND project_id = %s",
            (version_id, req.agent_id, project_id),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    row["rag_config"] = row["rag_config"] or None  # stored as {} when the version has no RAG
    return PromptVersionOut.model_validate(row)


async def _rag_target(
    conn: Conn, req: CallRequested, project_id: uuid.UUID, version: PromptVersionOut
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """The effective RAG setup (run override, else the version's) and the KB's decrypted secrets.

    Retrieval loads exactly the index pinned in ``test_runs.config["rag_index_id"]``; if that is
    missing, not ready or built for another chunking/model, the item fails (no fallback).
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT config FROM test_runs WHERE id = %s", (req.run_id,))
        run_config = ((await cur.fetchone()) or {}).get("config") or {}
        raw = run_config["rag"] if "rag" in run_config else version.rag_config
        if not raw:
            return None
        cfg = RagConfig.model_validate(raw)
        if cfg.mode == "off":
            # nothing is retrieved, but the transcript still reaches the hosted caller and judge:
            # the simulator must be told about a KB that is (now) local-only
            await cur.execute(
                "SELECT local_only FROM knowledge_bases WHERE id = %s AND project_id = %s",
                (cfg.kb_id, project_id),
            )
            off_kb = await cur.fetchone()
            if off_kb is None or off_kb["local_only"] is False:
                return None
            return {
                "config": cfg.model_dump(mode="json"),
                "index_id": None,
                "kb_id": str(cfg.kb_id),
                "local_only": True,
            }, {}
        await cur.execute(
            "SELECT local_only, secrets_encrypted FROM knowledge_bases "
            "WHERE id = %s AND project_id = %s",
            (cfg.kb_id, project_id),
        )
        kb = await cur.fetchone()
        if kb is None:
            raise SpecNotFoundError("the run's knowledge base does not exist")
        kb_secrets: dict[str, str] = {}
        if kb["secrets_encrypted"]:
            try:
                kb_secrets = _secret_box().decrypt(bytes(kb["secrets_encrypted"]).decode())
            except (SecretDecryptError, RuntimeError, ValueError) as exc:
                raise SpecNotFoundError("the knowledge base secrets cannot be decrypted") from exc
        rag: dict[str, Any] = {
            "config": cfg.model_dump(mode="json"),
            "index_id": None,
            "kb_id": str(cfg.kb_id),
            "local_only": bool(kb["local_only"]),
        }
        if cfg.mode == "full_context":
            # live documents only; same predicate as rag.documents.active_document_ids
            await cur.execute(
                "SELECT filename, text FROM kb_documents "
                "WHERE kb_id = %s AND project_id = %s AND deleted_at IS NULL ORDER BY filename, id",
                (cfg.kb_id, project_id),
            )
            rag["full_context_text"] = "".join(
                f"\n\n# {d['filename']}\n{d['text']}" for d in await cur.fetchall()
            )
            return rag, kb_secrets
        index_id = run_config.get("rag_index_id")
        if not index_id:
            raise SpecNotFoundError("the run did not pin a knowledge base index")
        await cur.execute(
            "SELECT index_key, status FROM kb_indexes "
            "WHERE id = %s AND kb_id = %s AND project_id = %s",
            (index_id, cfg.kb_id, project_id),
        )
        idx = await cur.fetchone()
    if idx is None or idx["status"] != "ready" or idx["index_key"] != index_key(cfg):
        raise SpecNotFoundError("the pinned knowledge base index is not ready or does not match")
    rag["index_id"] = str(index_id)
    rag["index"] = await get_or_load(
        str(index_id), lambda: _load_index(conn, index_id, cfg.kb_id, project_id)
    )
    return rag, kb_secrets


async def _load_index(
    conn: Conn, index_id: uuid.UUID | str, kb_id: uuid.UUID, project_id: uuid.UUID
) -> LoadedIndex:
    """All chunks of one index (soft-deleted documents included: the build snapshotted them)."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT c.id, c.document_id, d.filename, c.text, c.start_char, c.end_char, "
            "c.parent_start, c.parent_end, c.embedding FROM kb_chunks c "
            "JOIN kb_documents d ON d.id = c.document_id "
            "WHERE c.index_id = %s AND d.kb_id = %s AND d.project_id = %s "
            "ORDER BY c.document_id, c.ordinal",
            (index_id, kb_id, project_id),
        )
        chunks = await cur.fetchall()
        await cur.execute(
            "SELECT id, text FROM kb_documents WHERE kb_id = %s AND project_id = %s "
            "AND id = ANY(%s)",
            (kb_id, project_id, list({c["document_id"] for c in chunks})),
        )
        docs = {str(d["id"]): d["text"] for d in await cur.fetchall()}
    return build_loaded_index(chunks, docs)


async def mark_in_progress(conn: Conn, run_item_id: uuid.UUID) -> None:
    await conn.execute(
        "UPDATE run_items SET status = 'in_progress' WHERE id = %s AND status = 'connecting'",
        (run_item_id,),
    )


#: Where ``give_up_item`` moves an item from each status it accepts. Before or during the call
#: the failure is the platform's (``error``, with an ``infra_error`` call); after it, the call
#: exists and only its evaluation was lost (``judge_error``).
_GIVE_UP_TO = {
    "queued": "error",
    "connecting": "error",
    "in_progress": "error",
    "completed": "judge_error",
    "evaluating": "judge_error",
}
#: Statuses that hold one of the run's concurrency slots (``runs.slots.ACTIVE_ITEM_STATUSES``).
SLOT_STATUSES = frozenset(ACTIVE_ITEM_STATUSES)


async def give_up_item(
    conn: Conn,
    run_item_id: uuid.UUID,
    reason: str,
    *,
    statuses: frozenset[str] = SLOT_STATUSES,
    stale_before: datetime | None = None,
) -> str | None:
    """End a run item nothing will move on any more; returns its new status, or ``None``.

    One transaction on ``conn`` (autocommit, or a savepoint inside an open transaction). Locks the
    run, then the item (the order of ``start_item`` and ``save_call``), and only acts while the
    item is still in one of ``statuses``, so of two racing callers (the simulator, the
    reconciler, a late worker saving its call) exactly one wins and the slot is released once.
    An ``error`` item gets an ``infra_error`` call so it counts as an infrastructure failure,
    not as an agent failure. With ``stale_before``, an item whose call started at or after it is
    left alone (it was resumed or opened since the caller looked).
    """
    reason = reason[:500]
    async with conn.transaction():
        cur = await conn.execute("SELECT run_id FROM run_items WHERE id = %s", (run_item_id,))
        found = await cur.fetchone()
        if found is None:
            return None
        run_id = found[0]
        cur = await conn.execute(
            "SELECT project_id, agent_id FROM test_runs WHERE id = %s FOR UPDATE", (run_id,)
        )
        run = await cur.fetchone()
        cur = await conn.execute(
            "SELECT status FROM run_items WHERE id = %s FOR UPDATE", (run_item_id,)
        )
        item = await cur.fetchone()
        if run is None or item is None or item[0] not in statuses or item[0] not in _GIVE_UP_TO:
            return None
        if stale_before is not None:
            cur = await conn.execute(
                "SELECT started_at FROM calls WHERE run_item_id = %s", (run_item_id,)
            )
            call = await cur.fetchone()
            if call is not None and call[0] >= stale_before:
                return None
        new_status = _GIVE_UP_TO[item[0]]
        await conn.execute(
            "UPDATE run_items SET status = %s, last_error = %s WHERE id = %s",
            (new_status, reason, run_item_id),
        )
        if new_status == "error":
            # the row a late worker's open_call would create is created here instead
            await conn.execute(
                "INSERT INTO calls (id, project_id, source, status, agent_id, run_item_id, "
                "end_reason, error, metadata, ended_at) "
                "VALUES (%s, %s, 'simulation', 'error', %s, %s, 'infra_error', %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET status = 'error', end_reason = 'infra_error', "
                "error = EXCLUDED.error, ended_at = now() WHERE calls.status = 'in_progress'",
                (
                    call_id_for(run_item_id),
                    run[0],
                    run[1],
                    run_item_id,
                    reason,
                    Jsonb({"run_id": str(run_id)}),
                ),
            )
        if item[0] in SLOT_STATUSES:
            await release_slot(conn, run_id)
        await enqueue(
            conn,
            make_envelope(
                ProgressEvent(
                    kind="item.status", run_id=run_id, run_item_id=run_item_id, status=new_status
                ),
                producer="run-items",
                correlation_id=str(run_id),
            ),
        )
        return new_status


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
) -> bool:
    """Write the finished call, its turns, tool calls and usage; finish the item; free the slot.

    Returns ``False``, writing nothing, when the item no longer holds its slot: it was given up on
    (``give_up_item``) while this call ran, so the late result is discarded and the slot, already
    released, is not released again.
    """
    call_id = spec.call_id
    status = "error" if result.end_reason in ("infra_error", "connect_failed") else "completed"
    # run, then item: the lock order of start_item and give_up_item
    await tx.execute("SELECT 1 FROM test_runs WHERE id = %s FOR UPDATE", (req.run_id,))
    cur = await tx.execute(
        "UPDATE run_items SET status = %s, last_error = %s "
        "WHERE id = %s AND status IN ('connecting', 'in_progress') RETURNING id",
        ("error" if status == "error" else "completed", result.error, req.run_item_id),
    )
    if await cur.fetchone() is None:
        return False
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
            "INSERT INTO retrievals (call_id, turn_idx, rag_config, index_id, query, queries, "
            "results, context_chars, timings, usage) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    call_id,
                    r.turn_idx,
                    Jsonb(r.rag_config),
                    r.index_id,
                    r.query,
                    Jsonb(r.queries),
                    Jsonb(r.results),
                    r.context_chars,
                    Jsonb(r.timings),
                    Jsonb(r.usage),
                )
                for r in result.retrievals
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
    await release_slot(tx, req.run_id)
    return True
