"""EVAL-04b acceptance: audit real recordings (real Gnani batch STT + DeepSeek) without the stack.

For each recording: decode -> Gnani diarized batch STT -> role detection (first-speaker rule +
DeepSeek check) -> turns -> DeepSeek judge, then print the role-detection verdict, the review
reasons it caused and the stored-equivalent ``needs_human_review``. Keys come from the
environment; they are never printed.

    python scripts/audit_role_review_demo.py --out proof/EVAL-04b/run.json REC.wav [REC2.wav ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import uuid  # noqa: E402

from pareeksha.audit.ingest import decode_audio  # noqa: E402
from pareeksha.audit.roles import detect_roles, role_review_reasons  # noqa: E402
from pareeksha.audit.turns import build_turns, label_segments  # noqa: E402
from pareeksha.evaluation.evaluator import CallSnapshot, evaluate_call  # noqa: E402
from pareeksha.evaluation.judge import AgentInfo  # noqa: E402
from pareeksha.evaluation.types import Turn  # noqa: E402
from pareeksha.llm.factory import build_client  # noqa: E402
from pareeksha.speech import get_stt_provider  # noqa: E402


async def audit(path: Path, language: str) -> dict[str, object]:
    audio = decode_audio(path.read_bytes())
    stt = get_stt_provider()
    llm = build_client()
    try:
        transcript = await stt.transcribe(
            audio.mixed_wav, language, diarize=True, num_speakers=2, bias_words=["EMI"]
        )
        segments = label_segments(transcript.segments)
        decision = await detect_roles(
            segments,
            llm,
            agent_name="EMI reminder bot",
            language=language,
            agent_description="Calls borrowers about an overdue EMI.",
        )
        event = {"event": "role_detection", **decision.to_event()}
        reasons = role_review_reasons([event])
        turns = [
            Turn(t.idx, t.speaker, t.start_ms, t.end_ms, t.text, t.text)
            for t in build_turns(segments, decision.roles)
        ]
        snap = CallSnapshot(
            call_id=uuid.uuid4(),
            agent=AgentInfo(name="EMI reminder bot", description="Calls borrowers about an EMI."),
            turns=turns,
            language=language,
            expected_language=language,
            allowed_languages=[language],
            review_reasons=reasons,
        )
        record = await evaluate_call(snap, llm)
    finally:
        await stt.aclose()
        await llm.aclose()
    return {
        "recording": path.name,
        "stt_seconds": transcript.usage.audio_seconds,
        "turns": [[t.idx, t.speaker, t.text[:90]] for t in turns],
        "role_detection": event,
        "review_reasons_from_roles": reasons,
        "judge_status": record.status,
        "overall_score": record.overall_score,
        "needs_human_review": record.needs_human_review,
        "review_reasons": record.review_reasons,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recordings", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--language", default="en-IN")
    args = ap.parse_args()
    results = [await audit(p, args.language) for p in args.recordings]
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in results:
        print(
            r["recording"],
            r["role_detection"]["llm_confidence"],  # type: ignore[index]
            "agrees" if r["role_detection"]["agrees_with_heuristic"] else "DISAGREES",  # type: ignore[index]
            "->",
            "needs_human_review" if r["needs_human_review"] else "no review",
            r["review_reasons"],
        )


if __name__ == "__main__":
    asyncio.run(main())
