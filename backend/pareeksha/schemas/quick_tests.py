"""Quick tests ("Test my prompt") and the in-app assistant.

A quick test takes a system prompt and some test data about a user, finds the rules in the prompt
(what the bot must never do or always do), writes test conversations for them, runs them against
the prompt and reports, per rule, whether the bot kept it and where it broke it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from pareeksha.schemas.common import RequestModel
from pareeksha.schemas.prompts import PromptTool

MAX_PROMPT_CHARS = 60_000
MAX_USER_DETAILS_CHARS = 10_000
RULE_ID = r"^[a-z0-9_]{1,40}$"

RuleKind = Literal["forbidden", "required"]
RuleStatus = Literal["pending", "kept", "broken", "not_tested"]
QuickTestStatus = Literal["running", "checking", "done", "failed"]


# -- what the planner model returns ----------------------------------------------------------------


class PlannedRule(BaseModel):
    """One rule the planner found in the prompt."""

    id: str = Field(pattern=RULE_ID)
    kind: RuleKind
    text: str = Field(min_length=1, max_length=300, description="the rule in plain words")
    source: str = Field(
        default="", max_length=300, description="the prompt line it comes from, or 'built-in'"
    )


class PlannedScenario(BaseModel):
    """One test conversation, and the rules it is meant to test."""

    title: str = Field(min_length=1, max_length=200)
    caller_goal: str = Field(min_length=1, max_length=2000)
    fixtures: dict[str, Any] = Field(default_factory=dict)
    reveal_rules: str = Field(default="", max_length=1000)
    success_criteria: str = Field(min_length=1, max_length=1000)
    must_say: list[str] = Field(default_factory=list, max_length=8)
    must_not_say: list[str] = Field(default_factory=list, max_length=8)
    max_turns: int = Field(default=10, ge=4, le=16)
    tags: list[str] = Field(default_factory=list, max_length=4)
    rule_ids: list[str] = Field(default_factory=list, max_length=10)


class QuickTestPlan(BaseModel):
    """The rules found in the prompt and the conversations that test them."""

    agent_name: str = Field(min_length=1, max_length=80)
    summary: str = Field(default="", max_length=600, description="what the bot does")
    language: str = Field(default="en-IN", min_length=2, max_length=20)
    rules: list[PlannedRule] = Field(min_length=1, max_length=20)
    scenarios: list[PlannedScenario] = Field(min_length=1, max_length=12)
    tools: list[PromptTool] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def _consistent(self) -> QuickTestPlan:
        """Rule ids, scenario titles and tool names are unique; scenarios cite known rules."""
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        titles = [s.title for s in self.scenarios]
        if len(titles) != len(set(titles)):
            raise ValueError("scenario titles must be unique")
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        known = set(ids)
        for s in self.scenarios:
            unknown = [r for r in s.rule_ids if r not in known]
            if unknown:
                raise ValueError(f"scenario {s.title!r} cites unknown rules {unknown}")
        return self


# -- per-call rule check (judge model output) ----------------------------------------------------


class JudgedRule(BaseModel):
    """The judge's verdict on one rule in one transcript."""

    rule_id: str = Field(pattern=RULE_ID)
    verdict: Literal["kept", "broken", "not_relevant"]
    turn: int | None = Field(default=None, description="transcript turn where it was broken")
    quote: str = Field(default="", max_length=400)
    why: str = Field(default="", max_length=400)


class CallJudgement(BaseModel):
    """Every rule's verdict for one transcript."""

    verdicts: list[JudgedRule] = Field(default_factory=list, max_length=20)


# -- improvement -----------------------------------------------------------------------------------


class DocSuggestion(BaseModel):
    """A fix for one knowledge-base document (or a new one)."""

    document: str = Field(max_length=300, description="file name, or 'new document'")
    problem: str = Field(max_length=600)
    suggestion: str = Field(max_length=4000, description="text to add or the corrected text")


class ImprovementDraft(BaseModel):
    """What the model suggests (the stored improvement adds token counts and the re-test id)."""

    summary: str = Field(max_length=800)
    improved_prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    changes: list[str] = Field(default_factory=list, max_length=12)
    doc_suggestions: list[DocSuggestion] = Field(default_factory=list, max_length=8)


class QuickTestImprovement(ImprovementDraft):
    """A stored rewrite: the draft plus sizes and the re-test it started."""

    instructions: str = ""
    prompt_chars_before: int = 0
    prompt_chars_after: int = 0
    retest_id: UUID | None = None


class ImproveRequest(RequestModel):
    """What to change in the prompt, and whether to test the result."""

    instructions: str = Field(
        default="",
        max_length=2000,
        examples=["Make the prompt shorter and stop it sharing the balance"],
    )
    retest: bool = Field(default=False, description="also test the improved prompt right away")


# -- create / read ---------------------------------------------------------------------------------


class QuickTestCreate(RequestModel):
    """A prompt, test customer data and optional documents to test."""

    system_prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    user_details: str = Field(
        default="",
        max_length=MAX_USER_DETAILS_CHARS,
        description="test data about the customer the bot talks to (name, account, balance...); "
        "added to the prompt as the customer record, or in place of {{user_details}}",
    )
    kb_id: UUID | None = Field(default=None, description="documents the bot answers from (RAG)")
    scenario_count: int = Field(default=8, ge=3, le=12)
    instructions: str = Field(default="", max_length=2000, description="what to focus on")
    confirm_cost: bool = Field(
        default=False, description="run even when the estimate is above the auto-run limit"
    )
    plan: QuickTestPlan | None = Field(
        default=None,
        description="the plan from an earlier 402 confirm_cost answer, so it is not made twice",
    )


class CostEstimate(BaseModel):
    """The estimate shown when a test is above the auto-run limit."""

    conversations: int
    est_cost: float
    limit: float


class QuickTestCreated(BaseModel):
    """The new test, its run and the estimated cost."""

    id: UUID
    run_id: UUID
    conversations: int
    est_cost: float


class RuleEvidence(BaseModel):
    """Where the bot broke a rule: the conversation, the turn and its words."""

    call_id: UUID
    scenario: str
    turn: int | None = None
    quote: str = ""
    why: str = ""


class RuleResult(BaseModel):
    """One rule with how many checked conversations kept or broke it."""

    id: str
    kind: RuleKind
    text: str
    source: str = ""
    status: RuleStatus
    broken: int = 0
    kept: int = 0
    evidence: list[RuleEvidence] = Field(default_factory=list)


class Conversation(BaseModel):
    """One test conversation's state for the results page."""

    item_id: UUID
    call_id: UUID | None = None
    scenario: str
    tests: list[str] = Field(default_factory=list, description="rule ids it was written for")
    status: Literal["waiting", "running", "checking", "done", "error"]
    broken_rules: list[str] = Field(default_factory=list)
    score: float | None = None
    error: str | None = None


class QuickTestProgress(BaseModel):
    """Conversations in the test, ended, checked and failed."""

    total: int = 0
    finished: int = 0
    checked: int = 0
    errors: int = 0


class QuickTestOut(BaseModel):
    """A prompt test with its rules, conversations and last improvement."""

    id: UUID
    name: str
    status: QuickTestStatus
    created_at: datetime
    agent_id: UUID
    run_id: UUID
    parent_id: UUID | None = None
    kb_id: UUID | None = None
    summary: str = ""
    language: str = ""
    system_prompt: str
    user_details: str
    prompt_chars: int
    est_cost: float | None = None
    progress: QuickTestProgress
    rules: list[RuleResult]
    conversations: list[Conversation]
    improvement: QuickTestImprovement | None = None


class QuickTestListItem(BaseModel):
    """A prompt test in the recent list."""

    id: UUID
    name: str
    status: QuickTestStatus
    created_at: datetime
    parent_id: UUID | None = None
    rules_total: int
    rules_broken: int
    conversations: int
    finished: int


class SetupKb(BaseModel):
    """A knowledge base the test screen can offer, and whether it is indexed."""

    id: UUID
    name: str
    documents: int
    ready: bool


class QuickTestSetup(BaseModel):
    """What the "Test my prompt" screen needs before the first test."""

    llm_ready: bool
    llm_provider: str
    agent_model: str
    auto_run_limit: float
    knowledge_bases: list[SetupKb]


# -- assistant -------------------------------------------------------------------------------------


class AssistantMessage(RequestModel):
    """One chat turn sent to the assistant."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)


class AssistantRequest(RequestModel):
    """The chat so far, the page the user is on and the test in view."""

    messages: list[AssistantMessage] = Field(min_length=1, max_length=30)
    page: str = Field(default="", max_length=200, description="the page the user is on")
    quick_test_id: UUID | None = Field(default=None, description="the test the user is looking at")

    @model_validator(mode="after")
    def _total_size(self) -> AssistantRequest:
        """At most 120k characters over all messages."""
        if sum(len(m.content) for m in self.messages) > 2 * MAX_PROMPT_CHARS:
            raise ValueError("messages are too long in total")
        return self


class TextSource(BaseModel):
    """Where in the user's messages a pasted text is: message number and its first/last words."""

    message: int = Field(ge=0)
    start: str = Field(default="", max_length=200)
    end: str = Field(default="", max_length=200)


class AssistantAction(BaseModel):
    """What the assistant wants done: start a test, improve one, or open a page."""

    type: Literal["start_quick_test", "improve_quick_test", "open_page"]
    prompt_from: TextSource | None = None
    use_default_rag_prompt: bool = False
    user_details_from: TextSource | None = None
    user_details: str = Field(default="", max_length=MAX_USER_DETAILS_CHARS)
    kb_id: UUID | None = None
    quick_test_id: UUID | None = None
    instructions: str = Field(default="", max_length=2000)
    retest: bool = True
    path: str = Field(default="", max_length=200)


class AssistantReply(BaseModel):
    """What the assistant model returns."""

    reply: str = Field(max_length=4000)
    action: AssistantAction | None = None
    suggestions: list[str] = Field(default_factory=list, max_length=4)


class AssistantResponse(BaseModel):
    """The assistant's reply and the outcome of its action."""

    reply: str
    suggestions: list[str] = Field(default_factory=list)
    action: Literal["start_quick_test", "improve_quick_test", "open_page"] | None = None
    quick_test_id: UUID | None = None
    improvement: QuickTestImprovement | None = None
    open_path: str | None = None
    pending: QuickTestCreate | None = Field(
        default=None, description="a test waiting for the user to accept its cost"
    )
    estimate: CostEstimate | None = None
    error: str | None = None
