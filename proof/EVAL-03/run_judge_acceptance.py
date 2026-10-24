"""EVAL-03 real-API acceptance: judge two synthetic calls with DeepSeek (no mocks).

Run:  cd backend && python ../proof/EVAL-03/run_judge_acceptance.py
Writes judge_output_*.json (full EvaluationRecord incl. raw judge JSON), usage.jsonl.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

from pareeksha.evaluation.evaluator import CallSnapshot, evaluate_call
from pareeksha.llm.client import UsageRecord
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.factory import build_client
from tests.fixtures import synthetic_calls as sc

OUT = Path(__file__).parent
LEDGER = OUT / "usage.jsonl"


def sink(record: UsageRecord) -> None:
    with LEDGER.open("a") as fh:
        fh.write(record.model_dump_json() + "\n")


async def run(name: str, snap: CallSnapshot, client) -> None:  # type: ignore[no-untyped-def]
    rec = await evaluate_call(snap, client)
    data = dataclasses.asdict(rec)
    data["id"], data["call_id"] = str(rec.id), str(rec.call_id)
    data["checks"] = [c.to_dict() for c in rec.checks]
    cited = sorted({i for d in rec.dimensions.values() for i in d["evidence_turns"]})
    valid = {t.idx for t in snap.turns}
    data["cited_turn_indices"] = cited
    data["all_cited_turns_exist"] = set(cited) <= valid
    (OUT / f"judge_output_{name}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str)
    )
    print(
        f"{name}: status={rec.status} score={rec.overall_score} passed={rec.passed} "
        f"critical={rec.critical_failure} review={rec.needs_human_review} "
        f"reasons={rec.review_reasons} failure_types={rec.failure_types} cited={cited} "
        f"tokens={rec.input_tokens}/{rec.output_tokens}"
    )


async def main() -> None:
    LEDGER.unlink(missing_ok=True)
    settings = LLMSettings(
        cost_deepseek_per_1k_input_tokens=0.00132, cost_deepseek_per_1k_output_tokens=0.00396
    )
    client = build_client(settings, usage_sink=sink)
    await run("wrong_amount", sc.wrong_amount_call(), client)
    await run("clean", sc.clean_call(), client)
    await client.aclose()


asyncio.run(main())
