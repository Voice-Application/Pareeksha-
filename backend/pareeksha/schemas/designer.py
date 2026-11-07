"""Test designer chat (docs/06-api-spec.md section 14)."""

from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from pareeksha.schemas.common import (
    AdapterType,
    Disclosure,
    ExpectedTool,
    ForbiddenPhrase,
    RequestModel,
)
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

MAX_MESSAGE_CHARS = 20_000
MAX_TOTAL_CHARS = 60_000


MAX_REGEX_CHARS = 200
_QUANT = r"(?:[+*?]|\{\d*(?:,\d*)?\})"
_GROUP = re.compile(r"\(([^()]*)\)\s*(" + _QUANT + r")?")
_REPEATS = re.compile(_QUANT + "|\\|")  # a quantifier, or alternation (`(a|a)+` backtracks too)


def unsafe_regex(pattern: str) -> str | None:
    """Why a model-written regex is refused (too long, not a regex, or a quantified group that
    itself repeats or alternates, such as ``(a+)+``, ``(a+){1,1000}`` or ``(a|a)+``), else
    ``None``. Deliberately conservative: any quantifier on such a group is refused, bounded or not.
    ponytail: a syntactic check, not a proof; run checks with a timeout if user regexes grow."""
    if len(pattern) > MAX_REGEX_CHARS:
        return f"longer than {MAX_REGEX_CHARS} characters"
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"does not compile ({exc})"
    flat = re.sub(r"\\.", "x", pattern)  # escaped characters are plain
    while match := _GROUP.search(flat):
        inner = bool(_REPEATS.search(match.group(1)))
        outer = bool(match.group(2)) and match.group(2) != "?"
        if inner and outer:
            return "nested quantifiers (catastrophic backtracking)"
        flat = flat[: match.start()] + ("a+" if inner or outer else "a") + flat[match.end() :]
    return None


class DraftAgent(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    languages: list[str] = Field(default_factory=list)
    endpoint_url: str | None = Field(
        default=None, description="required to commit; null while the assistant still has to ask"
    )
    adapter: AdapterType = "audio_v1"
    glass_box: bool = False
    mandatory_disclosures: list[Disclosure] = Field(default_factory=list)
    forbidden_phrases: list[ForbiddenPhrase] = Field(default_factory=list)
    expected_tools: list[ExpectedTool] = Field(default_factory=list)
    bias_list: list[str] = Field(default_factory=list)

    @field_validator("mandatory_disclosures", "forbidden_phrases")
    @classmethod
    def _regexes_are_safe(cls, items: list[Any]) -> list[Any]:
        for item in items:
            if item.regex and (reason := unsafe_regex(item.regex)):
                raise ValueError(f"regex of {item.id!r} {reason}")
        return items


class DraftScenario(ScenarioCreate):
    """A scenario of the draft; it is bound to the new agent on commit."""

    agent_id: None = None


class ExistingPersona(RequestModel):
    existing_id: UUID


class NewPersona(RequestModel):
    new: PersonaCreate


class DesignerDraft(RequestModel):
    agent: DraftAgent
    scenarios: list[DraftScenario] = Field(min_length=1, max_length=30)
    personas: list[ExistingPersona | NewPersona] = Field(min_length=1, max_length=10)
    noise_profile_ids: list[UUID] = Field(min_length=1, max_length=8)


class ChatTurn(RequestModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class DesignerChatRequest(RequestModel):
    messages: list[ChatTurn] = Field(min_length=1, max_length=40)
    draft: DesignerDraft | None = None

    @model_validator(mode="after")
    def _total_size(self) -> DesignerChatRequest:
        if sum(len(m.content) for m in self.messages) > MAX_TOTAL_CHARS:
            raise ValueError(f"messages are longer than {MAX_TOTAL_CHARS} characters in total")
        return self


class DesignerQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1)
    options: list[str] = Field(default_factory=list, max_length=8)


class DesignerChatResponse(BaseModel):
    reply: str
    questions: list[DesignerQuestion] = Field(default_factory=list, max_length=5)
    draft: DesignerDraft | None = None
    ready: bool = False


class DesignerCommitRequest(RequestModel):
    draft: DesignerDraft


class DesignerCommitResult(BaseModel):
    agent_id: UUID
    scenario_ids: list[UUID]
    persona_ids: list[UUID]
    noise_profile_ids: list[UUID]
    calls: int
    run_wizard_path: str
