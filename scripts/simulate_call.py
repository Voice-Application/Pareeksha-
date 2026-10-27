"""Run ONE simulated call end to end (VOICE-04 acceptance): real Gnani STT/TTS, real LLM caller.

Starts the mock EMI agent (``python -m mock_agent.server``, optional planted bug) unless
``--agent-url`` points at another ``pareeksha-audio-v1`` agent, then runs ``CallRunner`` with the
speech providers named by ``STT_PROVIDER`` / ``TTS_PROVIDER`` (default gnani) and the caller brain
named by ``LLM_PROVIDER`` (default deepseek). Writes to ``<out>``: ``caller.wav``, ``agent.wav``,
``mixed.wav``, ``transcript.json`` (turns, tool calls, events, usage), ``transcript.txt`` and
``usage.json``. Keys come from the environment / ``.env``; they are never printed.

    python scripts/simulate_call.py --out proof/VOICE-04/calls/00_clean \
        --persona "Priya" --scenario "Disputes" --profile pstn_8k_alaw
    python scripts/simulate_call.py --out proof/VOICE-04/calls/01_false_waiver \
        --bug false_waiver --persona "Arjun" --scenario "Prompt-injection"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from pareeksha.adapters.base import AgentTarget  # noqa: E402
from pareeksha.audio.profiles import get_profile  # noqa: E402
from pareeksha.llm.caller import CallerBrain  # noqa: E402
from pareeksha.llm.client import FileJSONCache  # noqa: E402
from pareeksha.llm.factory import build_client  # noqa: E402
from pareeksha.schemas.personas import PersonaCreate  # noqa: E402
from pareeksha.schemas.scenarios import ScenarioCreate  # noqa: E402
from pareeksha.simulation.models import CallResult, CallSpec  # noqa: E402
from pareeksha.simulation.runner import CallRunner  # noqa: E402
from pareeksha.simulation.runtime import BrainCallerSource  # noqa: E402
from pareeksha.speech import get_stt_provider, get_tts_provider  # noqa: E402

SEED_DATA = ROOT / "backend" / "pareeksha" / "seed" / "data"


def pick(items: list[dict[str, Any]], key: str, needle: str) -> dict[str, Any]:
    hits = [i for i in items if needle.lower() in str(i[key]).lower()]
    if len(hits) != 1:
        raise SystemExit(f"{needle!r} matches {len(hits)} of {[i[key] for i in items]}")
    return hits[0]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_mock_agent(bug: str, log_path: Path) -> tuple[subprocess.Popen[bytes], str]:
    port = free_port()
    env = {**os.environ, "MOCK_AGENT_PORT": str(port), "MOCK_BUGS": bug, "PYTHONPATH": str(ROOT / "backend")}
    log = log_path.open("wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "mock_agent.server"], cwd=ROOT, env=env, stdout=log, stderr=log
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return proc, f"ws://127.0.0.1:{port}/call"
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("mock agent did not start")


def render_text(result: CallResult, persona: PersonaCreate, scenario: ScenarioCreate) -> str:
    lines = [
        f"persona: {persona.name} ({persona.language}, interruption {persona.interruption_level})",
        f"scenario: {scenario.title}",
        f"end_reason: {result.end_reason}   duration: {result.duration_ms / 1000:.1f} s",
        "",
    ]
    for t in result.turns:
        tag = " [barge-in]" if t.is_barge_in else ""
        lines.append(f"[{t.idx:02d}] {t.start_ms / 1000:6.2f}-{t.end_ms / 1000:6.2f}s {t.speaker:6s}{tag}")
        lines.append(f"       text: {t.text}")
        if t.speaker == "caller" and t.agent_heard_text is not None:
            lines.append(f"       agent heard: {t.agent_heard_text}")
        if t.speaker == "agent" and t.glass_box_text:
            lines.append(f"       agent said (glass box): {t.glass_box_text}")
    for c in result.tool_calls:
        lines.append(f"tool call @{c.at_ms / 1000:.2f}s (turn {c.turn_idx}): {c.name} {c.arguments} -> {c.result}")
    for b in result.barge_in_attempts:
        lines.append(
            f"barge-in: planned +{b.planned_offset_ms} ms after agent start {b.agent_speech_start_ms} ms, "
            f"scheduled {b.scheduled_ms} ms, started {b.started_ms} ms, cancelled={b.cancelled}"
        )
    return "\n".join(lines) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--persona", required=True, help="substring of a seed persona name")
    ap.add_argument("--scenario", required=True, help="substring of a seed scenario title")
    ap.add_argument("--profile", default="clean_16k")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--bug", default="", help="MOCK_BUGS value for the mock agent")
    ap.add_argument("--agent-url", default=None)
    ap.add_argument("--adapter", default="audio_v1", choices=["audio_v1", "pipecat"])
    ap.add_argument("--max-seconds", type=int, default=150)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    persona = PersonaCreate(**pick(yaml.safe_load((SEED_DATA / "personas.yaml").read_text()), "name", args.persona))
    scenario = ScenarioCreate(
        **pick(yaml.safe_load((SEED_DATA / "scenarios_emi.yaml").read_text()), "title", args.scenario)
    )
    proc = None
    url = args.agent_url
    if url is None:
        proc, url = start_mock_agent(args.bug, args.out / "mock_agent.log")
    llm_cache = FileJSONCache(args.out / "llm_cache")
    llm = build_client(cache=llm_cache)
    stt, tts = get_stt_provider(), get_tts_provider()
    spec = CallSpec(
        call_id=uuid.uuid4(),
        agent=AgentTarget(
            agent_id=uuid.uuid4(), adapter=args.adapter, endpoint_url=url, glass_box=True
        ),
        persona=persona,
        scenario=scenario,
        profile=get_profile(args.profile),
        seed=args.seed,
        max_call_seconds=args.max_seconds,
        metadata={"mock_bugs": [b for b in args.bug.split(",") if b]} if proc else {},
    )
    runner = CallRunner(stt=stt, tts=tts, caller=BrainCallerSource(CallerBrain(llm, seed=args.seed)))
    started = time.monotonic()
    try:
        outcome = await runner.run(spec)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
        await stt.aclose()
        await tts.aclose()
    result = outcome.save(args.out)
    (args.out / "transcript.txt").write_text(render_text(result, persona, scenario), encoding="utf-8")
    usage = [u.model_dump(mode="json") for u in result.usage]
    (args.out / "usage.json").write_text(json.dumps(usage, indent=2), encoding="utf-8")
    print(f"{args.out.name}: {result.end_reason} in {time.monotonic() - started:.0f} s, "
          f"{len(result.turns)} turns, {len(result.usage)} billed calls")


if __name__ == "__main__":
    asyncio.run(main())
