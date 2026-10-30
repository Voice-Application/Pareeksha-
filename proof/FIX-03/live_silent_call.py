"""FIX-03 live proof: ONE call of the "Caller goes silent" scenario, evaluated by the real judge.

Real Gnani STT/TTS, real DeepSeek (caller brain + judge), the mock EMI agent started as the repo
starts it (`python -m mock_agent.server`). No database or Kafka: the call is built the way
`simulation/store.read_spec` builds it and the evaluation is the same `evaluate_call` the evaluator
worker runs, over the same turns the worker would read back.

Run from the repo root with GNANI_API_KEY and DEEPSEEK_API_KEY in the environment:
    python proof/FIX-03/live_silent_call.py proof/FIX-03/live_call.json
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import yaml
from pareeksha.adapters.base import AgentTarget
from pareeksha.audio.profiles import get_profile
from pareeksha.evaluation.evaluator import CallSnapshot, evaluate_call
from pareeksha.evaluation.judge import AgentInfo
from pareeksha.evaluation.pg_stores import expected_amounts_from_fixtures
from pareeksha.evaluation.pii import mask_pii
from pareeksha.evaluation.types import (
    Disclosure,
    ForbiddenPhrase,
    ToolCall,
    as_turn,
)
from pareeksha.llm.caller import CallerBrain
from pareeksha.llm.factory import build_client
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate
from pareeksha.seed.runner import DATA_DIR
from pareeksha.simulation.models import CallSpec
from pareeksha.simulation.runner import CallRunner, quiet_pipecat_logs
from pareeksha.simulation.runtime import BrainCallerSource
from pareeksha.speech.registry import get_stt_provider, get_tts_provider

PERSONA = "The Silent One"
SCENARIO = "Caller goes silent"
PORT = 8791


def load(name: str) -> list[dict]:
    return yaml.safe_load((DATA_DIR / name).read_text(encoding="utf-8"))


async def main(out: Path) -> None:
    agent_yaml = yaml.safe_load(
        (DATA_DIR / "agent_emi.yaml").read_text(encoding="utf-8")
    )
    persona = PersonaCreate.model_validate(
        next(p for p in load("personas.yaml") if p["name"] == PERSONA)
    )
    agent_id = uuid.uuid4()
    scenario = ScenarioCreate.model_validate(
        {
            **next(s for s in load("scenarios_emi.yaml") if s["title"] == SCENARIO),
            "agent_id": agent_id,
        }
    )
    env = {**os.environ, "MOCK_AGENT_PORT": str(PORT), "PYTHONPATH": "."}
    agent_proc = subprocess.Popen([sys.executable, "-m", "mock_agent.server"], env=env)
    try:
        for _ in range(60):
            try:
                if (
                    httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1).status_code
                    == 200
                ):
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise RuntimeError("mock agent did not come up")
        spec = CallSpec(
            call_id=uuid.uuid4(),
            agent=AgentTarget(
                agent_id=agent_id,
                adapter="audio_v1",
                endpoint_url=f"ws://127.0.0.1:{PORT}/ws",
                adapter_config={},
                languages=agent_yaml["languages"],
                glass_box=True,
            ),
            persona=persona,
            scenario=scenario,
            profile=get_profile("clean_16k"),
            seed=7,
            max_call_seconds=agent_yaml["max_call_seconds"],
        )
        quiet_pipecat_logs()
        llm = build_client()
        runner = CallRunner(
            stt=get_stt_provider(),
            tts=get_tts_provider(),
            caller=BrainCallerSource(CallerBrain(llm)),
        )
        outcome = await runner.run(spec)
        result = outcome.result
        print(
            f"call {spec.call_id} end_reason={result.end_reason} error={result.error}"
        )

        turns = [
            as_turn(
                {
                    "idx": t.idx,
                    "speaker": t.speaker,
                    "start_ms": t.start_ms,
                    "end_ms": t.end_ms,
                    "text": t.text,
                    "text_masked": mask_pii(t.text),
                    "ground_truth_text": t.ground_truth_text
                    or (t.glass_box_text if t.speaker == "agent" else t.text),
                    "agent_heard_text": t.agent_heard_text,
                    "language_detected": t.language_detected,
                    "is_barge_in": t.is_barge_in,
                }
            )
            for t in result.turns
        ]
        evaluation = None
        if result.end_reason not in ("infra_error", "connect_failed"):
            snap = CallSnapshot(
                call_id=spec.call_id,
                agent=AgentInfo(
                    name=agent_yaml["name"],
                    description=agent_yaml["description"],
                    mandatory_disclosures=[
                        Disclosure.from_dict(d)
                        for d in agent_yaml["mandatory_disclosures"]
                    ],
                    forbidden_phrases=[
                        ForbiddenPhrase.from_dict(d)
                        for d in agent_yaml["forbidden_phrases"]
                    ],
                ),
                turns=turns,
                language=persona.language,
                scenario=scenario,
                persona=persona,
                tool_calls=[
                    ToolCall(name=c.name, args=c.arguments, turn_idx=c.turn_idx)
                    for c in result.tool_calls
                ],
                expected_language=persona.language,
                allowed_languages=[persona.language],
                expected_tool_calls=list(scenario.expected_tool_calls) or None,
                expected_amounts=expected_amounts_from_fixtures(scenario.fixtures)
                or None,
            )
            evaluation = await evaluate_call(snap, llm)
        doc = {
            "call_id": str(spec.call_id),
            "scenario": SCENARIO,
            "persona": PERSONA,
            "end_reason": result.end_reason,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "turns": [t.model_dump() for t in result.turns],
            "silence_events": [
                e.model_dump()
                for e in result.events
                if e.type in ("caller_silence", "caller_tts", "caller_pause")
            ],
            "evaluation": None
            if evaluation is None
            else {
                "status": evaluation.status,
                "overall_score": evaluation.overall_score,
                "passed": evaluation.passed,
                "critical_failure": evaluation.critical_failure,
                "failure_types": evaluation.failure_types,
                "summary": evaluation.summary,
                "judge_model": evaluation.judge_model,
                "dimensions": evaluation.dimensions,
                "checks": [c.__dict__ for c in evaluation.checks],
                "metrics": evaluation.metrics.__dict__,
            },
        }
        out.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print(f"wrote {out}")
    finally:
        agent_proc.terminate()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
