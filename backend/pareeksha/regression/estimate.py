"""Cost estimate for a regression run (FR-RN-2) and the remaining budget check.

The figures are planning estimates from the scenarios' ``max_turns``, not measurements:
a caller turn is ~4 s of synthesised speech (~14 characters per second), an agent turn ~6 s of
audio to transcribe, a caller LLM call ~800 input / 60 output tokens, a judge call ~6000 / 1200.
Rates come from the ``COST_*`` settings; an unset rate counts as 0, so ``est_cost`` is then 0.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.db.models import ApiUsage
from pareeksha.llm.base import LLMUsage
from pareeksha.llm.config import LLMSettings
from pareeksha.schemas.runs import RunEstimate
from pareeksha.speech.config import SpeechSettings

CALLER_TURN_SECONDS = 4.0
AGENT_TURN_SECONDS = 6.0
TTS_CHARS_PER_SECOND = 14.0
CALLER_PROMPT_TOKENS = (800, 60)
JUDGE_TOKENS = (6000, 1200)


def estimate_run(
    max_turns: Sequence[int],
    *,
    speech: SpeechSettings | None = None,
    llm: LLMSettings | None = None,
) -> RunEstimate:
    """One entry of ``max_turns`` per call that will be placed."""
    speech = speech or SpeechSettings()
    llm = llm or LLMSettings()
    caller_turns = sum(math.ceil(t / 2) for t in max_turns)
    agent_turns = sum(t // 2 for t in max_turns)
    tts_seconds = caller_turns * CALLER_TURN_SECONDS
    stt_seconds = agent_turns * AGENT_TURN_SECONDS
    judge_calls = len(max_turns)
    tts_cost = tts_seconds * TTS_CHARS_PER_SECOND / 1000 * (speech.cost_tts_per_1k_chars or 0.0)
    stt_cost = stt_seconds / 60 * (speech.cost_stt_stream_per_min or 0.0)
    caller_cost = llm.estimate_cost(
        LLMUsage(
            input_tokens=caller_turns * CALLER_PROMPT_TOKENS[0],
            output_tokens=caller_turns * CALLER_PROMPT_TOKENS[1],
        )
    )
    judge_cost = llm.estimate_cost(
        LLMUsage(
            input_tokens=judge_calls * JUDGE_TOKENS[0], output_tokens=judge_calls * JUDGE_TOKENS[1]
        )
    )
    return RunEstimate(
        tts_seconds=round(tts_seconds, 1),
        stt_seconds=round(stt_seconds, 1),
        judge_calls=judge_calls,
        caller_llm_calls=caller_turns,
        est_cost=round(tts_cost + stt_cost + (caller_cost or 0.0) + (judge_cost or 0.0), 2),
    )


async def remaining_budget(session: AsyncSession) -> float | None:
    """``BUDGET_CREDITS`` minus recorded ``api_usage.est_cost``; ``None`` when no budget is set."""
    raw: Any = os.environ.get("BUDGET_CREDITS")
    if not raw:
        return None
    used = await session.scalar(select(func.coalesce(func.sum(ApiUsage.est_cost), 0)))
    return float(raw) - float(used or 0)
