from __future__ import annotations

import json
import uuid
from typing import Any

from pareeksha.evaluation.evaluator import CallSnapshot, EvaluationRecord
from pareeksha.evaluation.handlers import RunState
from pareeksha.events.schemas import RunCompletedSummary, RunFinalStatus
from pareeksha.llm.base import (
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMProvider,
    LLMProviderName,
    LLMUsage,
)
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMSettings


class ScriptedProvider(LLMProvider):
    name = LLMProviderName.DEEPSEEK

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = list(replies)
        self.requests: list[JSONCompletionRequest] = []

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return JSONCompletionResult(
            provider=self.name,
            model=request.model,
            text=reply,
            usage=LLMUsage(input_tokens=1000, output_tokens=200),
            latency_ms=12,
        )

    async def aclose(self) -> None:
        return None


def client_for(provider: ScriptedProvider) -> LLMClient:
    settings = LLMSettings(
        _env_file=None,
        deepseek_api_key="k",
        cost_deepseek_per_1k_input_tokens=0.001,
        cost_deepseek_per_1k_output_tokens=0.004,
    )
    return LLMClient(provider, settings)


def judge_json(
    scores: tuple[int, ...] = (4, 4, 4, 4, 4, 4, 4),
    *,
    evidence: list[int] | None = None,
    critical: bool = False,
    confidence: str = "high",
    failure_types: list[str] | None = None,
) -> str:
    keys = (
        "task_completion",
        "policy_compliance",
        "factual_accuracy",
        "language_handling",
        "conversation_flow",
        "empathy_tone",
        "escalation",
    )
    dims: dict[str, Any] = {
        k: {
            "score": s,
            "evidence_turns": [0] if evidence is None else evidence,
            "reason": "because",
        }
        for k, s in zip(keys, scores, strict=True)
    }
    return json.dumps(
        {
            "dimensions": dims,
            "critical_failure": critical,
            "needs_human_review": False,
            "failure_types": failure_types or [],
            "summary": "summary",
            "confidence": confidence,
        }
    )


class FakeEvaluatorStore:
    def __init__(self, snapshot: CallSnapshot | None) -> None:
        self.snapshot = snapshot
        self.saved: list[EvaluationRecord] = []

    async def load_snapshot(self, call_id: uuid.UUID) -> CallSnapshot | None:
        return self.snapshot

    async def save_evaluation(self, record: EvaluationRecord) -> None:
        self.saved.append(record)


class FakeFinalizerStore:
    def __init__(self, state: RunState | None) -> None:
        self.state = state
        self.claimed = False
        self.claims: list[tuple[RunFinalStatus, RunCompletedSummary]] = []

    async def load_run_state(self, run_id: uuid.UUID) -> RunState | None:
        return self.state

    async def claim_run_completion(
        self, run_id: uuid.UUID, status: RunFinalStatus, summary: RunCompletedSummary
    ) -> bool:
        if self.claimed:
            return False
        self.claimed = True
        self.claims.append((status, summary))
        return True
