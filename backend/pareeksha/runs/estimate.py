"""Run cost estimate and budget check (FR-RN-2, docs/06-api-spec.md section 3).

The estimate is a planning figure, not a quote: it assumes every call lasts as long as its
scenario's ``max_turns`` allows (capped by the agent's ``max_call_seconds``), so it errs high.
Prices come from the ``COST_*`` environment variables (``.env.example``); a rate that is not set
contributes 0, so the budget guard is only as strict as the rates the owner has measured.
The budget is ``BUDGET_CREDITS`` minus the ``api_usage.est_cost`` already spent.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from dataclasses import dataclass

from pareeksha.llm.base import LLMUsage
from pareeksha.llm.config import LLMSettings
from pareeksha.schemas.runs import RunEstimate
from pareeksha.speech.config import SpeechSettings

#: One conversational turn (caller or agent) takes about this long, including pauses.
SECONDS_PER_TURN = 6.0
#: Spoken characters per second, for the TTS bill (about 150 words per minute of Indian-language
#: speech, 6 characters per word).
CHARS_PER_SECOND = 15.0
#: The caller speaks every other turn.
CALLER_SHARE = 0.5
#: Tokens per caller-LLM call (system prompt + history in, one short utterance out).
CALLER_TOKENS_IN = 800
CALLER_TOKENS_OUT = 80
#: Tokens per judge call (rubric + masked transcript in, scores and evidence out).
JUDGE_TOKENS_IN = 4000
JUDGE_TOKENS_OUT = 800


@dataclass(frozen=True, slots=True)
class ScenarioShape:
    """What the estimate needs to know about one scenario."""

    max_turns: int


def call_seconds(max_turns: int, max_call_seconds: int) -> float:
    return min(max_turns * SECONDS_PER_TURN, float(max_call_seconds))


def estimate_run(
    scenarios: Sequence[ScenarioShape],
    *,
    cells_per_scenario: int,
    max_call_seconds: int,
    text_only: bool = False,
    speech: SpeechSettings | None = None,
    llm: LLMSettings | None = None,
) -> RunEstimate:
    """Estimate ``cells_per_scenario`` calls (personas x profiles x repeats) of every scenario.

    ``text_only`` is the dry run (PRD risk table): no TTS or STT, only the LLM calls.
    """
    speech = speech or SpeechSettings()
    llm = llm or LLMSettings()
    tts_seconds = 0.0
    stt_seconds = 0.0
    caller_calls = 0
    for scenario in scenarios:
        seconds = call_seconds(scenario.max_turns, max_call_seconds)
        tts_seconds += seconds * CALLER_SHARE * cells_per_scenario
        stt_seconds += seconds * cells_per_scenario  # both sides are transcribed
        caller_calls += math.ceil(scenario.max_turns * CALLER_SHARE) * cells_per_scenario
    judge_calls = len(scenarios) * cells_per_scenario
    if text_only:
        tts_seconds = stt_seconds = 0.0

    provider_tts = speech.tts_provider
    provider_stt = speech.stt_provider
    cost = speech.tts_cost(provider_tts, round(tts_seconds * CHARS_PER_SECOND)) or 0.0
    cost += speech.stt_cost(provider_stt, stt_seconds, "stt_stream") or 0.0
    cost += (
        llm.estimate_cost(
            LLMUsage(
                input_tokens=caller_calls * CALLER_TOKENS_IN + judge_calls * JUDGE_TOKENS_IN,
                output_tokens=caller_calls * CALLER_TOKENS_OUT + judge_calls * JUDGE_TOKENS_OUT,
            )
        )
        or 0.0
    )
    return RunEstimate(
        tts_seconds=round(tts_seconds, 1),
        stt_seconds=round(stt_seconds, 1),
        judge_calls=judge_calls,
        caller_llm_calls=caller_calls,
        est_cost=round(cost, 2),
    )


def budget_credits() -> float | None:
    """``BUDGET_CREDITS`` (None when unset or blank: no budget guard)."""
    raw = os.environ.get("BUDGET_CREDITS", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def remaining_budget(spent: float, budget: float | None = None) -> float | None:
    budget = budget_credits() if budget is None else budget
    return None if budget is None else round(budget - spent, 2)


def is_over_budget(est_cost: float, remaining: float | None) -> bool:
    return remaining is not None and est_cost > remaining
