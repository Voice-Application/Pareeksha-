"""The LLM judge: renders ``judge_v1.j2``, calls the provider at temperature 0 with the pinned
judge model, and validates evidence against the transcript (one repair retry on failure)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field

from pareeksha.evaluation.evidence import evidence_problems
from pareeksha.evaluation.metrics import CallMetrics
from pareeksha.evaluation.pii import mask_pii
from pareeksha.evaluation.rubric import ANCHORS
from pareeksha.evaluation.types import CheckResult, Disclosure, ForbiddenPhrase, ToolCall, Turn
from pareeksha.llm.base import ChatMessage, LLMPurpose
from pareeksha.llm.client import GenerationResult, LLMClient
from pareeksha.llm.prompts import prompt_hash, render_prompt
from pareeksha.schemas.evaluation import JudgeOutput
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

JUDGE_PROMPT = "judge_v1"
JUDGE_MAX_OUTPUT_TOKENS = 2500


@dataclass(frozen=True)
class AgentInfo:
    name: str
    description: str = ""
    mandatory_disclosures: Sequence[Disclosure] = ()
    forbidden_phrases: Sequence[ForbiddenPhrase] = ()


@dataclass(frozen=True)
class JudgeInput:
    agent: AgentInfo
    turns: Sequence[Turn]
    metrics: CallMetrics
    checks: Sequence[CheckResult]
    call_language: str = "unknown"
    scenario: ScenarioCreate | None = None
    persona: PersonaCreate | None = None
    tool_calls: Sequence[ToolCall] = field(default_factory=tuple)


def mask_turn(turn: Turn) -> Turn:
    """Return ``turn`` with PII masked in every text field the judge can see."""

    def m(value: str | None) -> str | None:
        return None if value is None else mask_pii(value)

    return dataclasses.replace(
        turn,
        text_masked=mask_pii(turn.text_masked or turn.text),
        ground_truth_text=m(turn.ground_truth_text),
        agent_heard_text=m(turn.agent_heard_text),
    )


def render_judge_prompt(data: JudgeInput) -> str:
    return render_prompt(
        JUDGE_PROMPT,
        agent=data.agent,
        scenario=data.scenario,
        persona=data.persona,
        call_language=data.call_language,
        turns=[mask_turn(t) for t in data.turns],
        tool_calls=[
            {"name": t.name, "args": t.args, "turn_idx": t.turn_idx} for t in data.tool_calls
        ],
        metrics=data.metrics,
        checks=list(data.checks),
        rubric_anchors=ANCHORS,
    )


async def run_judge(client: LLMClient, data: JudgeInput) -> GenerationResult[JudgeOutput]:
    """Judge one call. Raises ``JSONGenerationError`` if the output stays invalid after the repair
    retry (the evaluator stores that as ``judge_error``)."""
    valid = {t.idx for t in data.turns}
    return await client.generate_json(
        purpose=LLMPurpose.JUDGE,
        messages=[ChatMessage(role="user", content=render_judge_prompt(data))],
        schema=JudgeOutput,
        prompt_hash=prompt_hash(JUDGE_PROMPT),
        temperature=0.0,
        max_output_tokens=JUDGE_MAX_OUTPUT_TOKENS,
        thinking=False,
        timeout_s=120.0,
        semantic_check=lambda out: evidence_problems(out, valid),
    )
