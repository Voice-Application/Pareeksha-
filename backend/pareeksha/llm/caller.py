"""Caller brain: the LLM that plays the simulated customer (``caller_v1.j2``)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from pareeksha.llm.base import ChatMessage, LLMPurpose
from pareeksha.llm.client import GenerationResult, LLMClient
from pareeksha.llm.prompts import prompt_hash, render_prompt
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

CALLER_PROMPT = "caller_v1"


@dataclass(frozen=True)
class HistoryLine:
    speaker: Literal["agent", "caller"]
    text: str


class CallerReply(BaseModel):
    utterance: str = Field(min_length=1, max_length=600)
    end_call: bool = False


class CallerBrain:
    """Produces the caller's next utterance from persona, scenario and the dialogue so far."""

    def __init__(self, client: LLMClient, *, seed: int = 0) -> None:
        self._client = client
        self.seed = seed

    async def next_utterance(
        self,
        persona: PersonaCreate,
        scenario: ScenarioCreate,
        history: Sequence[HistoryLine],
        *,
        turn_number: int | None = None,
    ) -> GenerationResult[CallerReply]:
        turn = (
            turn_number
            if turn_number is not None
            else 1 + sum(1 for h in history if h.speaker == "caller")
        )
        prompt = render_prompt(
            CALLER_PROMPT,
            persona=persona,
            scenario=scenario,
            history=history,
            turn_number=turn,
        )
        # The opening utterance is sampled at temperature 0 and cached per seed, so the same
        # seed reproduces the same first line (EVAL-01 acceptance); later turns use the
        # configured caller temperature but are cached per (seed, turn, dialogue) too.
        opening = not any(h.speaker == "caller" for h in history)
        settings = self._client.settings
        return await self._client.generate_json(
            purpose=LLMPurpose.CALLER,
            messages=[ChatMessage(role="user", content=prompt)],
            schema=CallerReply,
            prompt_hash=prompt_hash(CALLER_PROMPT),
            temperature=0.0 if opening else settings.temperature_for(LLMPurpose.CALLER),
            max_output_tokens=300,
            cache_salt=f"caller:{self.seed}:{turn}",
        )
