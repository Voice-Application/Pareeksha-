"""LLM "intent preserved" flag for one clip (FR-DI-3).

With an LLM configured, texts that are identical after normalisation need no call (the answer
is yes). Everything else is one small JSON-mode request through the provider-independent
``LLMClient`` (DeepSeek by default). The flag is optional: without an LLM client it stays ``None``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pareeksha.llm.base import ChatMessage, LLMPurpose
from pareeksha.llm.client import LLMClient
from pareeksha.llm.prompts import prompt_hash, render_prompt

INTENT_PROMPT = "asr_intent_v1"


class IntentVerdict(BaseModel):
    preserved: bool
    reason: str = Field(default="", max_length=400)


async def intent_preserved(
    client: LLMClient | None, *, reference: str, hypothesis: str, language: str, identical: bool
) -> bool | None:
    """``True`` / ``False`` from the judge, ``None`` when no LLM client is configured."""
    if client is None:
        return None  # all-null keeps the aggregate honest (never "yes" for the easy clips only)
    if identical:
        return True
    prompt = render_prompt(
        INTENT_PROMPT, reference=reference, hypothesis=hypothesis or "(nothing)", language=language
    )
    result = await client.generate_json(
        purpose=LLMPurpose.ASR_INTENT,
        messages=[ChatMessage(role="user", content=prompt)],
        schema=IntentVerdict,
        prompt_hash=prompt_hash(INTENT_PROMPT),
        temperature=0.0,
        max_output_tokens=200,
        thinking=False,
        timeout_s=60.0,
    )
    return result.parsed.preserved
