"""Generate ``N`` valid scenario drafts for an agent with the configured LLM (DeepSeek by default).

Requests above ``BATCH_SIZE`` are split into several calls so each answer stays short enough to be
complete. Every batch must come back with exactly the requested number of scenarios, the
requested categories, unique titles and only tools the agent declares; anything else is sent back
to the model once (``semantic_check`` -> the client's single repair retry).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from pareeksha.llm.base import ChatMessage, LLMPurpose
from pareeksha.llm.client import GenerationResult, LLMClient
from pareeksha.llm.prompts import prompt_hash, render_prompt
from pareeksha.schemas.scenarios import ScenarioCreate

SCENARIO_PROMPT = "scenario_gen_v1"
CATEGORIES = ("happy_path", "edge_case", "adversarial")
BATCH_SIZE = 10
#: Share of each category when the request gives no mix.
DEFAULT_SHARES = (0.3, 0.4, 0.3)
MAX_OUTPUT_TOKENS = 6000


class ScenarioBatch(BaseModel):
    scenarios: list[ScenarioCreate]


@dataclass(frozen=True)
class AgentBrief:
    name: str
    description: str = ""
    languages: Sequence[str] = ()
    tools: Sequence[Mapping[str, Any]] = ()
    disclosures: Sequence[Mapping[str, Any]] = ()
    forbidden: Sequence[Mapping[str, Any]] = ()


@dataclass
class Generated:
    scenarios: list[ScenarioCreate] = field(default_factory=list)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def resolve_mix(count: int, mix: Mapping[str, int]) -> dict[str, int]:
    """The requested mix, or a 30 / 40 / 30 split; always sums to ``count``."""
    if mix:
        return {k: int(v) for k, v in mix.items() if v > 0}
    happy = round(count * DEFAULT_SHARES[0])
    adversarial = round(count * DEFAULT_SHARES[2])
    edge = count - happy - adversarial
    return {k: v for k, v in zip(CATEGORIES, (happy, edge, adversarial)) if v > 0}


def split_batches(mix: Mapping[str, int], batch_size: int = BATCH_SIZE) -> list[dict[str, int]]:
    """Cut a mix into batches of at most ``batch_size``, keeping every batch's mix mixed."""
    remaining = dict(mix)
    total = sum(remaining.values())
    batches: list[dict[str, int]] = []
    n_batches = -(-total // batch_size)
    for b in range(n_batches):
        left = n_batches - b
        batch: dict[str, int] = {}
        for kind in list(remaining):
            take = -(-remaining[kind] // left)  # ceil: spread each category evenly
            if take:
                batch[kind] = take
                remaining[kind] -= take
        batches.append(batch)
    return [b for b in batches if sum(b.values())]


def batch_problems(
    batch: ScenarioBatch,
    mix: Mapping[str, int],
    brief: AgentBrief,
    taken_titles: set[str],
) -> str | None:
    """Why this batch is unusable, or ``None``. The text goes back to the model verbatim."""
    items = batch.scenarios
    want = sum(mix.values())
    if len(items) != want:
        return f"expected exactly {want} scenarios, got {len(items)}"
    titles = [s.title.strip().lower() for s in items]
    if len(set(titles)) != len(titles) or taken_titles & set(titles):
        return "titles must be unique and must not repeat existing scenarios"
    for kind, n in mix.items():
        got = sum(kind in s.tags for s in items)
        if got != n:
            return f"expected {n} scenarios tagged '{kind}', got {got}"
    tools = {str(t.get("name")) for t in brief.tools}
    for s in items:
        for call in s.expected_tool_calls:
            if tools and call.get("name") not in tools:
                return (
                    f"scenario '{s.title}' expects tool {call.get('name')!r}, which the agent "
                    f"does not declare (declared: {sorted(tools)})"
                )
            if not tools:
                return f"scenario '{s.title}' expects a tool call but the agent declares no tools"
    return None


async def generate_scenarios(
    client: LLMClient,
    brief: AgentBrief,
    count: int,
    mix: Mapping[str, int],
    existing_titles: Sequence[str] = (),
) -> Generated:
    """``count`` scenarios in the requested ``mix`` (see module doc). Raises the client's
    ``JSONGenerationError`` if a batch is still invalid after the repair retry."""
    plan = resolve_mix(count, mix)
    out = Generated()
    taken = {t.strip().lower() for t in existing_titles}
    for batch_mix in split_batches(plan):
        size = sum(batch_mix.values())
        prompt = render_prompt(
            SCENARIO_PROMPT,
            agent={
                "name": brief.name,
                "description": brief.description,
                "languages": list(brief.languages) or ["en-IN"],
                "tools": list(brief.tools),
                "disclosures": list(brief.disclosures),
                "forbidden": list(brief.forbidden),
            },
            count=size,
            mix=batch_mix,
            existing_titles=sorted(taken)[:60],
        )

        def check(
            b: ScenarioBatch,
            m: Mapping[str, int] = batch_mix,
            seen: frozenset[str] = frozenset(taken),
        ) -> str | None:
            return batch_problems(b, m, brief, set(seen))

        result: GenerationResult[ScenarioBatch] = await client.generate_json(
            purpose=LLMPurpose.SCENARIO_GEN,
            messages=[ChatMessage(role="user", content=prompt)],
            schema=ScenarioBatch,
            prompt_hash=prompt_hash(SCENARIO_PROMPT),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking=False,
            timeout_s=180.0,
            semantic_check=check,
        )
        out.calls += 1
        out.input_tokens += result.usage.input_tokens
        out.output_tokens += result.usage.output_tokens
        for scenario in result.parsed.scenarios:
            taken.add(scenario.title.strip().lower())
            out.scenarios.append(scenario)
    return out
