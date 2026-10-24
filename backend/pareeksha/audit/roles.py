"""Speaker role detection: first speaker heuristic, then an LLM check (TRD section 8).

The heuristic says the first speaker is the agent. The LLM reads the opening of the transcript and
returns a role for every speaker label. A confident LLM verdict wins (and the disagreement with the
heuristic is recorded); a low-confidence or unusable verdict falls back to the heuristic, and the
decision says so. Nothing here is silent: ``RoleDecision.method`` / ``note`` end up in the call's
event log.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from pareeksha.audit.turns import LabelledSegment, Role, labels_in_order
from pareeksha.evaluation.pii import mask_pii
from pareeksha.llm.base import ChatMessage, LLMPurpose
from pareeksha.llm.client import JSONGenerationError, LLMClient
from pareeksha.llm.config import LLMConfigError
from pareeksha.llm.prompts import prompt_hash, render_prompt

log = logging.getLogger(__name__)

ROLE_PROMPT = "role_detect_v1"
#: Only the opening of the call is needed to tell the roles apart (keeps the prompt cheap).
MAX_LINES = 12
MAX_CHARS_PER_LINE = 300


class RoleVerdict(BaseModel):
    speaker_roles: dict[str, Literal["agent", "caller"]]
    confidence: Literal["high", "medium", "low"]
    reason: str = Field(default="", max_length=400)


@dataclass(frozen=True)
class RoleDecision:
    roles: dict[str, Role]
    #: ``llm`` = the LLM verdict was used; ``heuristic`` = first speaker is the agent.
    method: Literal["llm", "heuristic"]
    heuristic: dict[str, Role]
    llm: dict[str, Role] | None = None
    llm_confidence: str | None = None
    #: ``None`` when there was no LLM verdict to compare with.
    agrees_with_heuristic: bool | None = None
    note: str = ""
    llm_model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost: float | None = None

    def to_event(self) -> dict[str, object]:
        """The ``calls.event_log`` entry."""
        return {
            "event": "role_detection",
            "method": self.method,
            "roles": self.roles,
            "heuristic": self.heuristic,
            "llm": self.llm,
            "llm_confidence": self.llm_confidence,
            "agrees_with_heuristic": self.agrees_with_heuristic,
            "note": self.note,
            "llm_model": self.llm_model,
        }


def heuristic_roles(segments: Sequence[LabelledSegment]) -> dict[str, Role]:
    """First speaker = agent, everyone else = caller."""
    labels = labels_in_order(segments)
    return {label: ("agent" if i == 0 else "caller") for i, label in enumerate(labels)}


def _verdict_problem(verdict: RoleVerdict, labels: Sequence[str]) -> str | None:
    if set(verdict.speaker_roles) != set(labels):
        return f"speaker_roles must have exactly the keys {sorted(labels)}"
    roles = set(verdict.speaker_roles.values())
    if len(labels) >= 2 and roles != {"agent", "caller"}:
        return "with two or more speakers there must be at least one agent and one caller"
    return None


def _prompt_lines(segments: Sequence[LabelledSegment]) -> list[dict[str, object]]:
    ordered = sorted(segments, key=lambda s: s.start_ms)[:MAX_LINES]
    return [
        {"label": s.label, "start_ms": s.start_ms, "text": mask_pii(s.text)[:MAX_CHARS_PER_LINE]}
        for s in ordered
    ]


async def detect_roles(
    segments: Sequence[LabelledSegment],
    client: LLMClient | None,
    *,
    agent_name: str = "voice agent",
    agent_description: str = "",
    language: str = "unknown",
) -> RoleDecision:
    """Role of every speaker label in ``segments``.

    Provider errors that are worth retrying (timeouts, 429, 5xx) propagate so the consumer can
    retry; a missing key or output that stays invalid after the repair retry degrades to the
    heuristic and says so in ``note``.
    """
    labels = labels_in_order(segments)
    heuristic = heuristic_roles(segments)
    if not labels:
        return RoleDecision({}, "heuristic", {}, note="no speech")
    if client is None:
        return RoleDecision(heuristic, "heuristic", heuristic, note="llm check not configured")

    try:
        result = await client.generate_json(
            purpose=LLMPurpose.ROLE_DETECT,
            messages=[
                ChatMessage(
                    role="user",
                    content=render_prompt(
                        ROLE_PROMPT,
                        agent_name=agent_name,
                        agent_description=agent_description,
                        language=language,
                        first_speaker=labels[0],
                        lines=_prompt_lines(segments),
                    ),
                )
            ],
            schema=RoleVerdict,
            prompt_hash=prompt_hash(ROLE_PROMPT),
            temperature=0.0,
            max_output_tokens=400,
            thinking=False,
            timeout_s=60.0,
            semantic_check=lambda v: _verdict_problem(v, labels),
        )
    except LLMConfigError as exc:
        return RoleDecision(heuristic, "heuristic", heuristic, note=f"llm check unavailable: {exc}")
    except JSONGenerationError as exc:
        return RoleDecision(
            heuristic, "heuristic", heuristic, note=f"llm verdict unusable: {str(exc)[:200]}"
        )

    verdict = result.parsed
    llm_roles: dict[str, Role] = dict(verdict.speaker_roles)
    agrees = llm_roles == heuristic

    def decision(
        roles: dict[str, Role], method: Literal["llm", "heuristic"], note: str
    ) -> RoleDecision:
        return RoleDecision(
            roles,
            method,
            heuristic,
            llm=llm_roles,
            llm_confidence=verdict.confidence,
            agrees_with_heuristic=agrees,
            note=note[:300],
            llm_model=result.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            est_cost=result.est_cost,
        )

    if verdict.confidence == "low":
        return decision(
            heuristic, "heuristic", f"llm confidence low, kept first-speaker rule: {verdict.reason}"
        )
    note = verdict.reason if agrees else f"llm overrides first-speaker rule: {verdict.reason}"
    return decision(llm_roles, "llm", note)
