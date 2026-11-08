"""RAG matrix, pricing and report schemas (plans/2026-11-07-rag-lab.md, Task 9)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from pareeksha.schemas.common import RequestModel
from pareeksha.schemas.rag import RagConfig

EntryKind = Literal["rag", "no_rag", "full_context"]


class Baselines(RequestModel):
    no_rag: bool = True
    full_context: bool = True


class RagMatrixCreate(RequestModel):
    agent_id: UUID
    prompt_version: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Version number of the agent's prompt to test; any existing version, active or not "
            "(404 if the agent has none with this number). Every run of the matrix executes this "
            "version; the agent's active version is not changed. Default: the active version."
        ),
    )
    configs: list[RagConfig] = Field(min_length=1, max_length=4)
    baselines: Baselines = Field(default_factory=Baselines)
    scenario_ids: list[UUID] = Field(min_length=1)
    persona_ids: list[UUID] = Field(min_length=1)
    noise_profile_ids: list[UUID] = Field(min_length=1)
    repeats: int = Field(default=1, ge=1, le=20)
    confirm_over_budget: bool = False

    @model_validator(mode="after")
    def _one_kb_retrieval_only(self) -> RagMatrixCreate:
        if len({c.kb_id for c in self.configs}) != 1:
            raise ValueError("all configs must use the same kb_id")
        if any(c.mode != "retrieval" for c in self.configs):
            raise ValueError('configs must have mode "retrieval"; use baselines for the others')
        return self


class RagMatrixEntry(BaseModel):
    label: str
    kind: EntryKind
    run_id: UUID | None = None
    status_note: str | None = None
    rag: dict[str, object] = Field(default_factory=dict)


class RagMatrixOut(BaseModel):
    id: UUID
    agent_id: UUID
    kb_id: UUID
    entries: list[RagMatrixEntry]
    created_at: datetime


# --- report ---------------------------------------------------------------------------------


class RetrievalStats(BaseModel):
    hit_rate: float | None = None
    hit_rate_ci: tuple[float, float] | None = None
    mrr: float | None = None
    context_precision: float | None = None


class GenerationStats(BaseModel):
    faithfulness: float | None = None
    n_judged: int = 0
    hallucination_rate: float | None = None
    hallucination_ci: tuple[float, float] | None = None
    answer_correct_rate: float | None = None
    refusal_correct_rate: float | None = None
    skipped: dict[str, int] = Field(default_factory=dict)


class LatencyStats(BaseModel):
    retrieval_p50: float | None = None
    retrieval_p95: float | None = None
    embed_p50: float | None = None
    search_p50: float | None = None
    rerank_p50: float | None = None
    rewrite_p50: float | None = None
    turn_p50: float | None = None
    turn_p95: float | None = None


class TokenStats(BaseModel):
    agent_input: float = 0
    agent_output: float = 0
    query_embedding: float = 0
    rerank: float = 0


class IndexOneTime(BaseModel):
    input_tokens: int = 0
    cost_inr: float | None = None


class Savings(BaseModel):
    inr: float = Field(description="per month, at monthly_conversations")
    pct: float


class ReportRow(BaseModel):
    label: str
    kind: EntryKind
    run_id: UUID | None = None
    run_status: str | None = None
    status_note: str | None = None
    n_calls: int = 0
    n_questions_with_truth: int = 0
    retrieval: RetrievalStats = Field(default_factory=RetrievalStats)
    generation: GenerationStats = Field(default_factory=GenerationStats)
    latency_ms: LatencyStats = Field(default_factory=LatencyStats)
    tokens_per_conversation: TokenStats = Field(default_factory=TokenStats)
    cost_per_conversation_inr: float | None = None
    index_one_time: IndexOneTime = Field(default_factory=IndexOneTime)
    monthly_cost_inr: float | None = None
    savings_vs_full_context: Savings | None = None
    savings_vs_no_rag: Savings | None = None
    token_savings_vs_full_context_pct: float | None = None


class Recommendation(BaseModel):
    label: str | None = Field(description="null when no config is eligible")
    reason: str


class RagReport(BaseModel):
    matrix_id: UUID
    monthly_conversations: int
    rows: list[ReportRow]
    recommendation: Recommendation


# --- pricing --------------------------------------------------------------------------------

PriceKind = Literal["llm", "embedding", "rerank"]


class PriceIn(RequestModel):
    kind: PriceKind
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_per_m_inr: float = Field(ge=0, description="₹ per 1M input tokens")
    output_per_m_inr: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _not_local(self) -> PriceIn:
        if self.kind != "llm" and self.provider == "local":
            raise ValueError("local models always cost 0")
        return self


class PriceOut(PriceIn):
    updated_at: datetime


class UnpricedModel(BaseModel):
    kind: PriceKind
    provider: str
    model: str


class PricingOut(BaseModel):
    prices: list[PriceOut]
    unpriced: list[UnpricedModel]
