"""EVAL-04 real-key acceptance: ONE synthetic two-speaker recording through the whole audit path.

    cd backend && python ../proof/EVAL-04/run_acceptance.py ../proof/EVAL-04

Real: Gnani Timbre v3.0 TTS (two synthetic voices, no human voices), Gnani Prisma batch STT with
diarization + denoise, DeepSeek role check and judge, Postgres, the HTTP API (ASGI), the blob
store. Not run here: Kafka (the consumer framework is covered by INFRA-02's tests; this script
calls the handlers the ``auditor`` / ``evaluator`` consumers register, in a transaction like the
framework's). Needs GNANI_API_KEY and DEEPSEEK_API_KEY in the environment (or .env) and a Postgres
server (DATABASE_URL, default the compose one).

Spend: 3 short TTS calls (~160 characters), one ~15 s batch STT job, 1 role-check + 2 judge calls.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import psycopg
from alembic import command
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from pareeksha.api.deps import get_blob_store
from pareeksha.api.main import app
from pareeksha.audit.pipeline import Auditor, AuditDeps
from pareeksha.db.session import get_session_factory, make_engine
from pareeksha.events.consumer import Ctx
from pareeksha.events.schemas import make_envelope, parse_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.llm.client import UsageRecord
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.factory import build_client
from pareeksha.seed.runner import seed_database
from pareeksha.speech import get_stt_provider, get_tts_provider
from pareeksha.speech.wav import pcm_to_wav
from pareeksha.storage.blob import LocalBlobStore
from pareeksha.workers.evaluator import evaluate
from tests.conftest import alembic_config

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "../proof/EVAL-04").resolve()
SERVER = os.environ.get("DATABASE_URL", "postgresql://pareeksha:pareeksha@localhost:5432/pareeksha")
LANGUAGE = "hi-IN"
# (speaker, Timbre voice, text): invented lender "Shakti Finance", invented numbers, TTS voices only
SCRIPT = [
    (
        "agent",
        "Shivani",
        "नमस्ते, मैं शक्ति फाइनेंस से बोल रही हूँ। यह कॉल रिकॉर्ड की जा रही है। "
        "आपकी ईएमआई चार हज़ार दो सौ रुपये है, जो शुक्रवार को देय है।",
    ),
    ("caller", "Shubham", "हाँ, मैं शुक्रवार को पैसे जमा कर दूँगा।"),
    ("agent", "Shivani", "धन्यवाद, मैंने आपका वादा दर्ज कर लिया है।"),
]
USAGE = OUT / "usage.jsonl"


def log(msg: str) -> None:
    print(msg, flush=True)


def ledger(entry: dict[str, Any]) -> None:
    with USAGE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def llm_sink(record: UsageRecord) -> None:
    ledger({"kind": "llm", **json.loads(record.model_dump_json())})


async def synthesize_call() -> bytes:
    """Three TTS calls (agent / caller / agent) joined with 0.7 s of silence into one mono WAV."""
    tts = get_tts_provider()
    pieces: list[np.ndarray] = []
    gap = np.zeros(int(0.7 * 16000), dtype="<i2")
    for speaker, voice, text in SCRIPT:
        result = await tts.synthesize(text, voice, LANGUAGE, sample_rate=16000)
        ledger(
            {
                "kind": "tts",
                "speaker": speaker,
                "voice": voice,
                "characters": len(text),
                "duration_s": result.duration_s,
                **result.usage.model_dump(mode="json"),
            }
        )
        pcm = np.frombuffer(result.audio[44:], dtype="<i2")
        pieces += [pcm, gap]
        log(f"tts {speaker}/{voice}: {len(text)} chars -> {result.duration_s:.1f}s")
    await tts.aclose()
    return pcm_to_wav(np.concatenate(pieces).tobytes(), 16000)


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    blobs_dir = OUT / "blobs"
    for stale in blobs_dir.rglob("*") if blobs_dir.exists() else []:
        if stale.is_file():
            stale.unlink()
    result: dict[str, Any] = {}

    # --- 0. database: fresh migrated DB + the real seed (rubric, agent, demo key)
    base = make_url(SERVER.replace("postgresql+psycopg://", "postgresql://"))
    name = f"eval04_accept_{secrets.token_hex(3)}"
    admin = base.set(drivername="postgresql").render_as_string(hide_password=False)
    url = base.set(database=name).render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        command.upgrade(alembic_config(url.replace("postgresql://", "postgresql+psycopg://")), "head")
        engine = make_engine(url.replace("postgresql://", "postgresql+psycopg://"), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        key = "pk_live_" + secrets.token_urlsafe(24)
        os.environ["PAREEKSHA_API_KEY"] = key
        seeded = await seed_database(factory)
        log(f"seeded: {seeded.created}")
        app.dependency_overrides[get_session_factory] = lambda: factory
        blobs = LocalBlobStore(blobs_dir)
        app.dependency_overrides[get_blob_store] = lambda: blobs
        headers = {"Authorization": f"Bearer {key}"}

        recording = OUT / "synthetic_call.wav"
        if recording.exists():  # re-runs reuse the recording instead of paying for TTS again
            wav = recording.read_bytes()
            log(f"reusing {recording.name} ({len(wav)} bytes), no TTS spend")
        else:
            USAGE.unlink(missing_ok=True)
            wav = await synthesize_call()
            recording.write_bytes(wav)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as api:
            agents = (await api.get("/api/v1/agents", headers=headers)).json()["items"]
            agent_id = next(a["id"] for a in agents if a["name"] == "EMI Reminder Bot")

            # --- 1. upload (FR-AU-1)
            resp = await api.post(
                "/api/v1/audits",
                data={"agent_id": agent_id, "language": LANGUAGE},
                files={"file": ("synthetic_call.wav", wav, "audio/wav")},
                headers=headers,
            )
            log(f"POST /audits -> {resp.status_code} {resp.text}")
            assert resp.status_code == 202
            call_id = resp.json()["call_id"]
            result["upload"] = {"status_code": resp.status_code, "call_id": call_id}

            pg = await psycopg.AsyncConnection.connect(libpq_url(url), autocommit=True)
            try:
                row = await (
                    await pg.execute(
                        "SELECT envelope FROM outbox_events WHERE topic = %s", ("pareeksha.audit.requested.v1",)
                    )
                ).fetchone()
                assert row is not None
                audit_env = parse_envelope(json.dumps(row[0]).encode())

                # --- 2. auditor with the real providers
                llm = build_client(
                    LLMSettings(
                        cost_deepseek_per_1k_input_tokens=0.00132,
                        cost_deepseek_per_1k_output_tokens=0.00396,
                    ),
                    usage_sink=llm_sink,
                )
                stt = get_stt_provider()
                real_transcribe = stt.transcribe

                async def traced(wav: bytes, language: str, **kw: Any) -> Any:
                    t = await real_transcribe(wav, language, **kw)
                    ledger(
                        {
                            "kind": "stt",
                            "kwargs": {k: v for k, v in kw.items()},
                            **t.usage.model_dump(mode="json"),
                        }
                    )
                    result["raw_stt_segments"] = [s.model_dump() for s in t.segments]
                    return t

                stt.transcribe = traced
                auditor = Auditor(
                    AuditDeps(blobs=blobs, stt_factory=lambda: stt, llm=llm, fetch=_no_fetch)
                )
                async with pg.transaction():
                    ctx = Ctx(pg, "auditor", "t", 0, 0, 1)
                    outputs = await auditor.handle(audit_env, ctx)
                completed = make_envelope(
                    outputs[0].payload, producer="auditor", correlation_id=call_id
                )
                log(f"auditor produced {completed.type.value}")

                async def dump(sql: str, *a: Any) -> list[dict[str, Any]]:
                    cur = pg.cursor(row_factory=dict_row)
                    await cur.execute(sql, a)
                    return await cur.fetchall()

                call = (await dump("SELECT * FROM calls WHERE id = %s", call_id))[0]
                turns = await dump(
                    "SELECT idx, speaker, start_ms, end_ms, is_barge_in, text, text_masked "
                    "FROM turns WHERE call_id = %s ORDER BY idx",
                    call_id,
                )
                result["after_audit"] = {"call": call, "turns": turns}
                for t in turns:
                    log(f"  turn {t['idx']} {t['speaker']:6} {t['start_ms']:>6}-{t['end_ms']:<6} {t['text']}")

                # --- 3. judge with the same rubric (FR-AU-4)
                async with pg.transaction():
                    ctx = Ctx(pg, "evaluator", "t", 0, 0, 1)
                    ev_out = await evaluate(completed, ctx, llm)
                ev1 = (await dump("SELECT e.*, rv.version FROM evaluations e JOIN rubric_versions rv ON rv.id = e.rubric_version_id WHERE call_id = %s", call_id))[0]
                checks1 = await dump(
                    "SELECT check_type, check_key, passed, detail FROM deterministic_checks "
                    "WHERE call_id = %s ORDER BY 1, 2",
                    call_id,
                )
                result["evaluation_1"] = {"evaluation": ev1, "checks": checks1}
                log(
                    f"evaluation 1: rubric={ev1['version']} score={ev1['overall_score']} "
                    f"passed={ev1['passed']} review={ev1['needs_human_review']} "
                    f"failure_types={ev1['failure_types']}"
                )
                result["evaluation_1_events"] = [e.payload.model_dump(mode="json") for e in ev_out]

                # --- 4. user override swaps the roles and re-evaluates (FR-AU-3)
                roles = call["speaker_map"]
                swapped = {k: ("caller" if v == "agent" else "agent") for k, v in roles.items()}
                resp = await api.post(
                    f"/api/v1/calls/{call_id}/speaker-map", json=swapped, headers=headers
                )
                log(f"POST speaker-map {swapped} -> {resp.status_code}")
                assert resp.status_code == 202
                requeued = (
                    await dump(
                        "SELECT envelope FROM outbox_events WHERE topic = %s "
                        "AND envelope->'payload'->>'call_id' = %s ORDER BY created_at",
                        "pareeksha.call.completed.v1",
                        call_id,
                    )
                )[-1]
                again = parse_envelope(json.dumps(requeued["envelope"]).encode())
                async with pg.transaction():
                    ctx = Ctx(pg, "evaluator", "t", 0, 0, 1)
                    ev_out2 = await evaluate(again, ctx, llm)
                turns2 = await dump(
                    "SELECT idx, speaker, text FROM turns WHERE call_id = %s ORDER BY idx", call_id
                )
                rows = await dump(
                    "SELECT e.*, rv.version FROM evaluations e JOIN rubric_versions rv "
                    "ON rv.id = e.rubric_version_id WHERE call_id = %s",
                    call_id,
                )
                checks2 = await dump(
                    "SELECT check_type, check_key, passed, detail FROM deterministic_checks "
                    "WHERE call_id = %s ORDER BY 1, 2",
                    call_id,
                )
                result["after_override"] = {
                    "speaker_map": swapped,
                    "turns": turns2,
                    "evaluation_rows": len(rows),
                    "evaluation": rows[0],
                    "checks": checks2,
                    "events": [e.payload.model_dump(mode="json") for e in ev_out2],
                }
                for t in turns2:
                    log(f"  turn {t['idx']} {t['speaker']:6} {t['text']}")
                log(
                    f"evaluation 2: rows={len(rows)} score={rows[0]['overall_score']} "
                    f"passed={rows[0]['passed']} review={rows[0]['needs_human_review']} "
                    f"failure_types={rows[0]['failure_types']}"
                )
                result["db_usage"] = await dump(
                    "SELECT provider, operation, units, unit_type, est_cost FROM api_usage "
                    "ORDER BY id"
                )
                await llm.aclose()
            finally:
                await pg.close()
        await engine.dispose()
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')

    (OUT / "acceptance_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    log("wrote acceptance_result.json")


async def _no_fetch(url: str) -> bytes:
    raise RuntimeError("uploads are read from the blob store")


asyncio.run(main())
