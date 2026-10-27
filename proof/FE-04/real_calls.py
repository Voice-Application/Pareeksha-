"""FE-03/FE-04 real-data harness. Run inside the backend image (see proof/FE-03/proof.md).

    python real_calls.py run <run_id>      # fill every item of a planned run with a scripted call
    python real_calls.py audit <agent_id>  # one upload-source call (diarised batch STT of a TTS clip)

What is real: Gnani TTS voices every turn (persona voice for the caller, a stock voice for the agent), the caller
audio goes through the platform's LineSimulator for the run item's noise profile, Gnani STT transcribes the caller
turns, the DeepSeek judge (`evaluate_call`, rubric-2026-10-v1) scores the call, the API serves everything back.
What is scripted: the agent's side of the conversation and the caller's words (the voice simulator, VOICE-05, is not
merged). Rows are written the way EVAL-03's pg stores will write them (docs/schema.sql columns).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import statistics
import sys
import uuid
import wave
from pathlib import Path

import numpy as np
import psycopg
from psycopg.types.json import Jsonb

from pareeksha.audio.line_simulator import LineSimulator
from pareeksha.audio.profiles import get_profile
from pareeksha.evaluation.evaluator import CallSnapshot, evaluate_call
from pareeksha.evaluation.judge import AgentInfo
from pareeksha.evaluation.metrics import compute_metrics
from pareeksha.evaluation.types import Disclosure, ForbiddenPhrase, ToolCall, Turn
from pareeksha.events.settings import libpq_url
from pareeksha.llm.client import UsageRecord
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.factory import build_client
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate
from pareeksha.speech.registry import get_stt_provider, get_tts_provider

sys.path.insert(0, str(Path(__file__).parent))
from scripts import HI, KN, LATENCY  # noqa: E402

DATA = Path(os.environ.get("DATA_DIR", "/data"))
LEDGER = Path(os.environ.get("LEDGER", str(DATA / "fe04_usage.jsonl")))
SR = 16000
AGENT_VOICE = {"kn-IN": "Vasudha", "hi-IN": "Shivani"}


def ledger(entry: dict) -> None:
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def llm_sink(record: UsageRecord) -> None:
    ledger({"kind": "llm", **json.loads(record.model_dump_json())})


def wav_to_f32(wav: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav)) as w:
        raw = w.readframes(w.getnframes())
        assert w.getframerate() == SR and w.getnchannels() == 1, (w.getframerate(), w.getnchannels())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def f32_to_wav(x: np.ndarray, sr: int = SR) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


async def retry(fn):  # type: ignore[no-untyped-def]
    """Gnani allows one active request at a time; a 429 means another request is still finishing, so wait and retry."""
    for attempt in range(8):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            if "429" not in str(exc) and "RATE_LIMITED" not in str(exc) or attempt == 7:
                raise
            await asyncio.sleep(4 + attempt * 2)


async def tts(provider, text: str, voice: str, language: str) -> np.ndarray:  # type: ignore[no-untyped-def]
    cache = DATA / "ttscache" / (hashlib.sha256(f"{voice}|{language}|{text}".encode()).hexdigest() + ".wav")
    if cache.exists():
        return wav_to_f32(cache.read_bytes())
    res = await retry(lambda: provider.synthesize(text, voice, language, sample_rate=SR))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(res.audio)
    ledger({"kind": "tts", "voice": voice, "language": language, "chars": len(text), "audio_s": round(res.duration_s, 2)})
    return wav_to_f32(res.audio)


def agent_info(row: dict) -> AgentInfo:
    return AgentInfo(
        name=row["name"],
        description=row["description"] or "",
        mandatory_disclosures=tuple(Disclosure.from_dict(d) for d in row["mandatory_disclosures"]),
        forbidden_phrases=tuple(ForbiddenPhrase.from_dict(d) for d in row["forbidden_phrases"]),
    )


def model_from(cls, row: dict):  # type: ignore[no-untyped-def]
    return cls.model_validate({k: v for k, v in row.items() if k in cls.model_fields})


async def build_call(item: dict, scenario_row: dict, persona_row: dict, noise_name: str, bug: bool, idx: int):  # type: ignore[no-untyped-def]
    """Voice the script, apply the line, transcribe the caller turns. Returns turns, audio tracks, tool call."""
    lang = persona_row["language"]
    scripts = (KN if lang == "kn-IN" else HI)[scenario_row["title"]][bug]
    lines, tool = scripts
    ttsp, sttp = get_tts_provider(), get_stt_provider()
    profile = get_profile(noise_name)
    agent_n = 0
    t_ms = 800
    turns: list[dict] = []
    caller_track = np.zeros(0, dtype=np.float32)
    agent_track = np.zeros(0, dtype=np.float32)
    seed = int(hashlib.sha256(f"{item['id']}".encode()).hexdigest()[:8], 16)

    def place(track: np.ndarray, start_ms: int, audio: np.ndarray) -> np.ndarray:
        start = int(start_ms * SR / 1000)
        if len(track) < start + len(audio):
            track = np.pad(track, (0, start + len(audio) - len(track)))
        track[start : start + len(audio)] = audio
        return track

    for i, (speaker, text) in enumerate(lines):
        if speaker == "agent":
            audio = await tts(ttsp, text, AGENT_VOICE[lang], lang)
            gap = 0 if i == 0 else LATENCY[bug][min(agent_n, 3)]
            agent_n += 1
            start = t_ms + gap
            agent_track = place(agent_track, start, audio)
            turns.append({"idx": i, "speaker": "agent", "text": text, "start_ms": start, "end_ms": start + int(len(audio) / SR * 1000)})
        else:
            clean = await tts(ttsp, text, persona_row["voice_id"], lang)
            heard_audio = LineSimulator.simulate(profile, clean, seed=seed + i) if not profile.is_identity else clean
            heard_audio = np.asarray(heard_audio, dtype=np.float32)
            tr = await retry(lambda: sttp.transcribe(f32_to_wav(heard_audio), lang))
            ledger({"kind": "stt", "language": lang, "audio_s": round(len(heard_audio) / SR, 2), "line": noise_name})
            start = t_ms + 600
            caller_track = place(caller_track, start, clean)
            turns.append(
                {
                    "idx": i,
                    "speaker": "caller",
                    "text": tr.text.strip() or text,
                    "ground_truth_text": text,
                    "agent_heard_text": tr.text.strip(),
                    "stt_confidence": tr.confidence,
                    "language_detected": lang,
                    "start_ms": start,
                    "end_ms": start + int(len(clean) / SR * 1000),
                }
            )
        t_ms = turns[-1]["end_ms"]
    n = max(len(caller_track), len(agent_track))
    caller_track = np.pad(caller_track, (0, n - len(caller_track)))
    agent_track = np.pad(agent_track, (0, n - len(agent_track)))
    return turns, caller_track, agent_track, tool


def wer(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[-1] / max(1, len(r))


def write_call(conn, item: dict, agent_id, project_id, lang: str, turns, caller, agent, tool, rec, source="simulation", run_id=None):  # type: ignore[no-untyped-def]
    rel = f"fe04/{uuid.uuid4().hex[:12]}"
    out = DATA / rel
    out.mkdir(parents=True, exist_ok=True)
    (out / "caller.wav").write_bytes(f32_to_wav(caller))
    (out / "agent.wav").write_bytes(f32_to_wav(agent))
    (out / "mixed.wav").write_bytes(f32_to_wav(np.clip(caller + agent, -1, 1)))
    duration = turns[-1]["end_ms"] + 800
    call_id = conn.execute(
        """INSERT INTO calls (id, project_id, agent_id, run_item_id, source, language, status, end_reason, duration_ms,
               recording_caller, recording_agent, recording_mixed, started_at)
           VALUES (%s,%s,%s,%s,%s,%s,'completed','goal_achieved',%s,%s,%s,%s, now() - interval '12 minutes') RETURNING id""",
        (rec.call_id, project_id, agent_id, item["id"], source, lang, duration, f"{rel}/caller.wav", f"{rel}/agent.wav", f"{rel}/mixed.wav"),
    ).fetchone()["id"]
    for t in turns:
        conn.execute(
            """INSERT INTO turns (call_id, idx, speaker, text, text_masked, ground_truth_text, agent_heard_text,
                   language_detected, start_ms, end_ms, stt_confidence, is_barge_in)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false)""",
            (call_id, t["idx"], t["speaker"], t["text"], t["text"], t.get("ground_truth_text"), t.get("agent_heard_text"),
             t.get("language_detected"), t["start_ms"], t["end_ms"], t.get("stt_confidence")),
        )
    if tool:
        conn.execute(
            "INSERT INTO tool_calls (call_id, turn_idx, seq, name, arguments, result, at_ms) VALUES (%s,%s,0,'record_promise_to_pay',%s,%s,%s)",
            (call_id, tool[0], Jsonb(tool[1]), Jsonb({"ok": True}), turns[tool[0]]["start_ms"] + 1200),
        )
    m = rec.metrics
    lat = [
        turns[i + 1]["start_ms"] - turns[i]["end_ms"]
        for i in range(len(turns) - 1)
        if turns[i]["speaker"] == "caller" and turns[i + 1]["speaker"] == "agent"
    ]
    conn.execute(
        """INSERT INTO call_metrics (call_id, first_greeting_ms, response_latency_p50_ms, response_latency_p90_ms,
               response_latency_p95_ms, response_latency_max_ms, barge_in_attempts, barge_in_honoured, silence_gaps_over_2s,
               turn_count, agent_talk_ratio, repeated_utterances, caller_asr_wer, latency_is_approximate, extra)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s)""",
        (call_id, m.first_greeting_latency_ms, m.response_latency_p50_ms, np.percentile(lat, 90) if lat else None,
         m.response_latency_p95_ms, max(lat) if lat else None, m.barge_in_attempts, m.barge_in_honoured,
         m.silence_gaps_over_2s, len(turns), m.agent_talk_ratio, m.repeated_utterances, m.caller_wer, Jsonb(m.to_dict())),
    )
    for c in rec.checks:
        conn.execute(
            """INSERT INTO deterministic_checks (call_id, check_type, check_key, must_pass, passed, evidence_turns, detail)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (call_id, c.check_type, c.check_key, c.must_pass, c.passed, list(c.evidence_turns), c.detail),
        )
    rubric_id = conn.execute("SELECT id FROM rubric_versions ORDER BY is_active DESC, created_at LIMIT 1").fetchone()["id"]
    conn.execute(
        """INSERT INTO evaluations (id, call_id, rubric_version_id, status, judge_model, temperature, prompt_hash, dimensions,
               overall_score, passed, critical_failure, needs_human_review, review_reasons, failure_types, summary, confidence,
               raw_response, input_tokens, output_tokens, latency_ms)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (rec.id, call_id, rubric_id, rec.status, rec.judge_model, rec.temperature, rec.prompt_hash, Jsonb(rec.dimensions),
         rec.overall_score, rec.passed, rec.critical_failure, rec.needs_human_review, rec.review_reasons, rec.failure_types,
         rec.summary, rec.confidence, Jsonb(rec.raw_response) if rec.raw_response else None, rec.input_tokens, rec.output_tokens, rec.latency_ms),
    )
    return call_id


def finalize_run(conn, run_id) -> dict:  # type: ignore[no-untyped-def]
    rows = conn.execute(
        """SELECT e.overall_score, e.passed, e.critical_failure, e.needs_human_review, e.failure_types, m.response_latency_p50_ms,
                  m.response_latency_p95_ms, m.barge_in_attempts, m.barge_in_honoured
           FROM run_items ri JOIN calls c ON c.run_item_id = ri.id JOIN evaluations e ON e.call_id = c.id
           LEFT JOIN call_metrics m ON m.call_id = c.id WHERE ri.run_id = %s AND e.status = 'ok'""",
        (run_id,),
    ).fetchall()
    rows = [tuple(r.values()) for r in rows]
    scores = [float(r[0]) for r in rows]
    tags: dict[str, int] = {}
    for r in rows:
        for t in r[4]:
            tags[t] = tags.get(t, 0) + 1
    att = sum(r[7] for r in rows)
    summary = {
        "pass_rate": round(sum(bool(r[1]) for r in rows) / len(rows), 4),
        "critical_failures": sum(bool(r[2]) for r in rows),
        "needs_review": sum(bool(r[3]) for r in rows),
        "score_mean": round(statistics.mean(scores), 2),
        "latency_p50_ms": int(statistics.median([r[5] for r in rows if r[5] is not None])),
        "latency_p95_ms": int(max(r[6] for r in rows if r[6] is not None)),
        "barge_in_honoured_rate": round(sum(r[8] for r in rows) / att, 4) if att else None,
        "top_failure_types": sorted(([k, v] for k, v in tags.items()), key=lambda kv: -kv[1])[:6],
        "score_distribution": [sum(min(int(s // 10), 9) == b for s in scores) for b in range(10)],
    }
    conn.execute("UPDATE test_runs SET status='completed', summary=%s, started_at=COALESCE(started_at, now()-interval '14 minutes'), finished_at=now() WHERE id=%s", (Jsonb(summary), run_id))
    return summary


async def run_mode(run_id: uuid.UUID) -> None:
    client = build_client(LLMSettings(cost_deepseek_per_1k_input_tokens=0.00132, cost_deepseek_per_1k_output_tokens=0.00396), usage_sink=llm_sink)
    with psycopg.connect(libpq_url(os.environ["DATABASE_URL"]), autocommit=False, row_factory=psycopg.rows.dict_row) as conn:
        run = conn.execute("SELECT project_id, agent_id FROM test_runs WHERE id=%s", (run_id,)).fetchone()
        agent = conn.execute("SELECT * FROM agents WHERE id=%s", (run["agent_id"],)).fetchone()
        items = conn.execute(
            """SELECT ri.id, ri.scenario_id, ri.persona_id, ri.noise_profile_id, s.title, n.name AS noise
               FROM run_items ri JOIN scenarios s ON s.id=ri.scenario_id JOIN noise_profiles n ON n.id=ri.noise_profile_id
               WHERE ri.run_id=%s ORDER BY ri.created_at, ri.id""",
            (run_id,),
        ).fetchall()
        for n, it in enumerate(items):
            if conn.execute("SELECT 1 FROM calls WHERE run_item_id=%s", (it["id"],)).fetchone():
                continue
            sc = conn.execute("SELECT * FROM scenarios WHERE id=%s", (it["scenario_id"],)).fetchone()
            pr = conn.execute("SELECT * FROM personas WHERE id=%s", (it["persona_id"],)).fetchone()
            # Plant a failure in roughly 40% of cells, deterministically (every item whose index is 0,2 or 5 mod 5... see below).
            bug = n % 5 in (1, 3)
            turns, caller, agent_a, tool = await build_call(it, sc, pr, it["noise"], bug, n)
            for t in turns:
                if t["speaker"] == "caller":
                    t["wer"] = wer(t["ground_truth_text"], t["agent_heard_text"])
            call_id = uuid.uuid4()
            snap = CallSnapshot(
                call_id=call_id,
                agent=agent_info(agent),
                turns=[Turn(idx=t["idx"], speaker=t["speaker"], start_ms=t["start_ms"], end_ms=t["end_ms"], text=t["text"], text_masked=t["text"],
                            ground_truth_text=t.get("ground_truth_text"), agent_heard_text=t.get("agent_heard_text"), language_detected=pr["language"]) for t in turns],
                language=pr["language"],
                scenario=model_from(ScenarioCreate, sc),
                persona=model_from(PersonaCreate, pr),
                tool_calls=[ToolCall("record_promise_to_pay", tool[1], tool[0])] if tool else [],
                expected_language=pr["language"],
                allowed_languages=tuple(agent["languages"]),
                expected_tool_calls=sc["expected_tool_calls"],
                expected_amounts={"emi_amount": sc["fixtures"]["emi_amount"]},
                agent_id=agent["id"],
                run_id=run_id,
                run_item_id=it["id"],
            )
            rec = await evaluate_call(snap, client)
            write_call(conn, it, agent["id"], run["project_id"], pr["language"], turns, caller, agent_a, tool, rec)
            conn.execute("UPDATE run_items SET status='evaluated' WHERE id=%s", (it["id"],))
            conn.commit()
            print(f"[{n + 1}/{len(items)}] {it['title'][:28]:28} {pr['name'][:12]:12} {it['noise']:22} bug={bug!s:5} -> {rec.overall_score} passed={rec.passed} crit={rec.critical_failure} tags={rec.failure_types}", flush=True)
        print(json.dumps(finalize_run(conn, run_id)))
        conn.commit()
    await client.aclose()


async def audit_mode(agent_id: uuid.UUID) -> None:
    """One upload-source call: a two-speaker TTS clip mixed to mono, transcribed with diarisation, judged, stored as source='upload'.

    This is what the auditor (EVAL-04, not merged) will do for POST /audits; the API route itself is still a 501 stub.
    """
    lang = "hi-IN"
    ttsp, sttp = get_tts_provider(), get_stt_provider()
    lines = HI["Disputes the EMI amount"][True][0]
    mixed = np.zeros(0, np.float32)
    for speaker, text in lines:
        a = await tts(ttsp, text, AGENT_VOICE[lang] if speaker == "agent" else "Shubham", lang)
        mixed = np.concatenate([mixed, np.zeros(int(0.6 * SR), np.float32), a])
    wav = f32_to_wav(mixed)
    tr = await retry(lambda: sttp.transcribe(wav, lang, diarize=True, num_speakers=2))
    ledger({"kind": "stt_batch_diarized", "language": lang, "audio_s": round(len(mixed) / SR, 2)})
    first = tr.segments[0].speaker
    smap = {sp: ("agent" if sp == first else "caller") for sp in {s.speaker for s in tr.segments}}
    turns = [
        {"idx": i, "speaker": smap[sg.speaker], "text": sg.text, "start_ms": int(sg.start_s * 1000), "end_ms": int(sg.end_s * 1000), "language_detected": lang}
        for i, sg in enumerate(tr.segments)
    ]
    client = build_client(LLMSettings(cost_deepseek_per_1k_input_tokens=0.00132, cost_deepseek_per_1k_output_tokens=0.00396), usage_sink=llm_sink)
    with psycopg.connect(libpq_url(os.environ["DATABASE_URL"]), autocommit=False, row_factory=psycopg.rows.dict_row) as conn:
        agent = conn.execute("SELECT * FROM agents WHERE id=%s", (agent_id,)).fetchone()
        call_id = uuid.uuid4()
        snap = CallSnapshot(
            call_id=call_id,
            agent=agent_info(agent),
            turns=[Turn(idx=t["idx"], speaker=t["speaker"], start_ms=t["start_ms"], end_ms=t["end_ms"], text=t["text"], text_masked=t["text"], language_detected=lang) for t in turns],
            language=lang,
            expected_language=lang,
            allowed_languages=tuple(agent["languages"]),
            agent_id=agent_id,
        )
        rec = await evaluate_call(snap, client)
        rel = f"fe04/audit_{uuid.uuid4().hex[:8]}"
        (DATA / rel).mkdir(parents=True, exist_ok=True)
        (DATA / rel / "original.wav").write_bytes(wav)
        conn.execute(
            """INSERT INTO calls (id, project_id, agent_id, source, language, status, end_reason, duration_ms, recording_original, recording_mixed,
                   speaker_map, metadata, started_at) VALUES (%s,%s,%s,'upload',%s,'completed','upload',%s,%s,%s,%s,%s, now() - interval '3 minutes')""",
            (call_id, agent["project_id"], agent_id, lang, int(len(mixed) / SR * 1000), f"{rel}/original.wav", f"{rel}/original.wav", Jsonb(smap), Jsonb({"file": "ravi_call_0412.wav"})),
        )
        for t in turns:
            conn.execute(
                """INSERT INTO turns (call_id, idx, speaker, text, text_masked, language_detected, start_ms, end_ms, is_barge_in)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,false)""",
                (call_id, t["idx"], t["speaker"], t["text"], t["text"], lang, t["start_ms"], t["end_ms"]),
            )
        m = rec.metrics
        conn.execute(
            """INSERT INTO call_metrics (call_id, first_greeting_ms, response_latency_p50_ms, response_latency_p95_ms, barge_in_attempts, barge_in_honoured,
                   silence_gaps_over_2s, turn_count, agent_talk_ratio, repeated_utterances, latency_is_approximate, extra)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s)""",
            (call_id, m.first_greeting_latency_ms, m.response_latency_p50_ms, m.response_latency_p95_ms, m.barge_in_attempts, m.barge_in_honoured,
             m.silence_gaps_over_2s, len(turns), m.agent_talk_ratio, m.repeated_utterances, Jsonb(m.to_dict())),
        )
        for c in rec.checks:
            conn.execute(
                "INSERT INTO deterministic_checks (call_id, check_type, check_key, must_pass, passed, evidence_turns, detail) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (call_id, c.check_type, c.check_key, c.must_pass, c.passed, list(c.evidence_turns), c.detail),
            )
        rubric_id = conn.execute("SELECT id FROM rubric_versions ORDER BY is_active DESC, created_at LIMIT 1").fetchone()["id"]
        conn.execute(
            """INSERT INTO evaluations (id, call_id, rubric_version_id, status, judge_model, temperature, prompt_hash, dimensions, overall_score, passed,
                   critical_failure, needs_human_review, review_reasons, failure_types, summary, confidence, raw_response, input_tokens, output_tokens, latency_ms)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (rec.id, call_id, rubric_id, rec.status, rec.judge_model, rec.temperature, rec.prompt_hash, Jsonb(rec.dimensions), rec.overall_score, rec.passed,
             rec.critical_failure, rec.needs_human_review, rec.review_reasons, rec.failure_types, rec.summary, rec.confidence,
             Jsonb(rec.raw_response) if rec.raw_response else None, rec.input_tokens, rec.output_tokens, rec.latency_ms),
        )
        conn.commit()
        print(f"audit call {call_id}: score={rec.overall_score} passed={rec.passed} tags={rec.failure_types}")
    await client.aclose()


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "run":
        asyncio.run(run_mode(uuid.UUID(sys.argv[2])))
    elif mode == "audit":
        asyncio.run(audit_mode(uuid.UUID(sys.argv[2])))
