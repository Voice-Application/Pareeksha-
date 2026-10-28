"""EVAL-01 real-API acceptance (DeepSeek default; one Gemini smoke call when GEMINI_API_KEY is set).

Run:  cd backend && python ../proof/EVAL-01/run_acceptance.py
Writes proof/EVAL-01/acceptance.json and usage.jsonl. Never prints key values.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from pydantic import BaseModel

from pareeksha.llm.base import ChatMessage, LLMProviderName, LLMPurpose
from pareeksha.llm.caller import CallerBrain, HistoryLine
from pareeksha.llm.client import FileJSONCache, LLMClient, UsageRecord
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.factory import build_client
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

OUT = Path(__file__).parent
LEDGER = OUT / "usage.jsonl"


class Verdict(BaseModel):
    sentiment: str
    confidence: float


def sink(record: UsageRecord) -> None:
    with LEDGER.open("a") as fh:
        fh.write(record.model_dump_json() + "\n")


# $ per 1k tokens from DeepSeek list prices (NOTES.md TL-01): flash 0.30/1.20 per 1M, pro 1.32/3.96.
def settings(provider: LLMProviderName = LLMProviderName.DEEPSEEK) -> LLMSettings:
    return LLMSettings(
        llm_provider=provider,
        cost_deepseek_per_1k_input_tokens=0.0003,
        cost_deepseek_per_1k_output_tokens=0.0012,
        gemini_judge_model=os.environ.get("GEMINI_JUDGE_MODEL") or "gemini-3.5-flash-lite",
        gemini_caller_model=os.environ.get("GEMINI_CALLER_MODEL") or "gemini-3.5-flash-lite",
    )


PERSONAS = {
    "kn": PersonaCreate(
        name="Lakshmamma, elderly",
        language="kn-IN",
        code_mix_style="none",
        voice_id="Lakshmi",
        emotion="confused",
        speed=0.85,
        behaviour_notes="Asks the agent to repeat; mishears numbers",
    ),
    "hi": PersonaCreate(
        name="Rohit, millennial",
        language="hi-IN",
        code_mix_style="heavy",
        voice_id="Shubham",
        emotion="neutral",
        behaviour_notes="Hinglish, UPI-savvy",
    ),
}
SCENARIO = ScenarioCreate(
    title="EMI promise to pay",
    caller_goal="Tell the agent you will pay the EMI on Friday and ask what happens if you are late",
    fixtures={"emi_amount": 4200, "due_date": "Friday", "loan_last4": "7788"},
    success_criteria="Agent records the promise to pay",
)


async def main() -> None:
    LEDGER.unlink(missing_ok=True)
    report: dict[str, object] = {}
    cfg = settings()

    # 1. schema-valid JSON on the judge model
    client = build_client(cfg, usage_sink=sink)
    res = await client.generate_json(
        purpose=LLMPurpose.ASR_INTENT,
        messages=[
            ChatMessage(
                role="user", content="Classify: 'ನಾನು ಶುಕ್ರವಾರ ಹಣ ಕಟ್ಟುತ್ತೇನೆ' (I will pay on Friday)."
            )
        ],
        schema=Verdict,
        max_output_tokens=100,
    )
    report["schema_valid"] = {
        "parsed": res.parsed.model_dump(),
        "model": res.model,
        "tokens": res.usage.model_dump(),
        "est_cost_usd": res.est_cost,
    }

    # 2. real repair round trip: reject the first answer once, force a second provider call
    rejected: list[str] = []

    def reject_first(v: Verdict) -> str | None:
        if not rejected:
            rejected.append(v.sentiment)
            return "sentiment must be exactly one of: positive, negative, neutral (lowercase)"
        return None if v.sentiment in {"positive", "negative", "neutral"} else "bad sentiment"

    rep = await client.generate_json(
        purpose=LLMPurpose.ASR_INTENT,
        messages=[ChatMessage(role="user", content="Sentiment of 'thanks, that was helpful'?")],
        schema=Verdict,
        semantic_check=reject_first,
        max_output_tokens=100,
    )
    report["repair"] = {
        "first_rejected": rejected[0],
        "final": rep.parsed.model_dump(),
        "repaired": rep.repaired,
        "tokens": rep.usage.model_dump(),
    }

    # 3. caller_v1: persona-language opening utterance, reproducible per seed
    cache_dir = OUT / "cache"
    shutil.rmtree(cache_dir, ignore_errors=True)
    cache = FileJSONCache(cache_dir)
    caller_client = LLMClient(client.provider, cfg, usage_sink=sink, cache=cache)
    greeting = [HistoryLine("agent", "Namaste, I am calling about your EMI of rupees 4200.")]
    out: dict[str, object] = {}
    for key, persona in PERSONAS.items():
        a = await CallerBrain(caller_client, seed=1).next_utterance(persona, SCENARIO, greeting)
        b = await CallerBrain(caller_client, seed=1).next_utterance(persona, SCENARIO, greeting)
        out[key] = {
            "utterance": a.parsed.utterance,
            "end_call": a.parsed.end_call,
            "same_seed_identical": a.parsed == b.parsed,
            "second_was_cache_hit": b.cache_hit,
            "model": a.model,
            "prompt_hash": a.prompt_hash,
        }
    # without the cache: is temperature-0 sampling reproducible on its own?
    nocache = LLMClient(client.provider, cfg, usage_sink=sink)
    x = await CallerBrain(nocache, seed=1).next_utterance(PERSONAS["kn"], SCENARIO, greeting)
    y = await CallerBrain(nocache, seed=1).next_utterance(PERSONAS["kn"], SCENARIO, greeting)
    out["kn_uncached_repeat_identical"] = x.parsed == y.parsed
    report["caller"] = out

    # 4. Gemini: one real smoke call (only if the key is present)
    if os.environ.get("GEMINI_API_KEY"):
        g_cfg = settings(LLMProviderName.GEMINI)
        g = build_client(g_cfg, usage_sink=sink)
        gr = await g.generate_json(
            purpose=LLMPurpose.ASR_INTENT,
            messages=[ChatMessage(role="user", content="Sentiment of 'thanks, that was helpful'?")],
            schema=Verdict,
            max_output_tokens=100,
        )
        report["gemini"] = {
            "parsed": gr.parsed.model_dump(),
            "model": gr.model,
            "tokens": gr.usage.model_dump(),
        }
        await g.aclose()
    else:
        report["gemini"] = "blocked: GEMINI_API_KEY is empty in this environment (needs H-01 key)"

    await client.aclose()
    (OUT / "acceptance.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


asyncio.run(main())
