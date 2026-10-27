"""Kafka handlers for the ``evaluator`` and ``finalizer`` consumer groups.

These are framework-independent coroutines: they take a typed envelope plus ports (``Protocol``
stores) and return the envelopes to produce. The consumer framework (INFRA-02) opens the DB
transaction, wraps the handler (``processed_events``, retry, DLQ) and passes a transaction-bound
store; ``events/consumer.py`` does not exist yet, so nothing is registered with it here (see
proof/EVAL-03/proof.md).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pareeksha.evaluation.evaluator import CallSnapshot, EvaluationRecord, evaluate_call
from pareeksha.events.schemas import (
    AnyEnvelope,
    CallCompleted,
    Envelope,
    EvaluationCompleted,
    EventType,
    ProgressEvent,
    RunCompleted,
    RunCompletedSummary,
    RunFinalStatus,
    RunKind,
    deterministic_event_id,
    make_envelope,
)
from pareeksha.llm.client import LLMClient
from pareeksha.regression.verdict import DEFAULT_TOLERANCE, regression_passed

#: ``call.completed`` end reasons with no usable conversation: nothing to evaluate. The run item
#: is already ``error``/``cancelled`` and the finalizer counts it from ``run_items``.
UNEVALUABLE_END_REASONS = frozenset({"connect_failed", "infra_error", "cancelled"})


class CallNotFoundError(ValueError):
    """The call named by the event does not exist (permanent: dead-letter it)."""


# ---------------------------------------------------------------------------------------------
# evaluator
# ---------------------------------------------------------------------------------------------


class EvaluatorStore(Protocol):
    """Transaction-bound storage port for the evaluator."""

    async def load_snapshot(self, call_id: uuid.UUID) -> CallSnapshot | None:
        """Masked-ready turns, agent config, scenario, persona and tool trace of the call."""

    async def save_evaluation(self, record: EvaluationRecord) -> None:
        """Upsert ``evaluations`` (unique call+rubric) and replace the call's
        ``deterministic_checks``; set ``run_items.status`` to ``evaluated`` or ``judge_error``
        (same transaction as the ``processed_events`` row)."""


async def handle_call_completed(
    env: Envelope[CallCompleted],
    store: EvaluatorStore,
    client: LLMClient,
    *,
    producer: str = "evaluator",
) -> list[AnyEnvelope]:
    """``call.completed`` -> evaluate -> ``evaluation.completed`` + progress ``call.evaluated``."""
    payload = env.payload
    if payload.end_reason in UNEVALUABLE_END_REASONS:
        return []
    snap = await store.load_snapshot(payload.call_id)
    if snap is None:
        raise CallNotFoundError(f"call {payload.call_id} not found")
    record = await evaluate_call(snap, client)
    await store.save_evaluation(record)

    completed = EvaluationCompleted(
        call_id=record.call_id,
        evaluation_id=record.id,
        status="ok" if record.status == "ok" else "judge_error",
        agent_id=payload.agent_id or snap.agent_id,
        run_id=payload.run_id or snap.run_id,
        run_item_id=payload.run_item_id or snap.run_item_id,
        overall_score=record.overall_score,
        passed=record.passed,
        critical_failure=record.critical_failure,
        needs_human_review=record.needs_human_review,
        failure_types=record.failure_types,
    )
    return evaluation_outputs(env, completed, producer=producer)


def evaluation_outputs(
    env: Envelope[CallCompleted], completed: EvaluationCompleted, *, producer: str = "evaluator"
) -> list[AnyEnvelope]:
    """``evaluation.completed`` plus, for a scored call, the ``call.evaluated`` progress event.

    Ids are ``uuid5(input_event_id, type)``, so building them again from a stored evaluation
    (a duplicate delivery after a crash) yields the same ids.
    """
    out: list[AnyEnvelope] = [
        make_envelope(
            completed,
            producer=producer,
            correlation_id=env.correlation_id,
            causation_id=env.event_id,
            event_id=deterministic_event_id(env.event_id, EventType.EVALUATION_COMPLETED),
        )
    ]
    if (
        completed.status == "ok"
        and completed.overall_score is not None
        and completed.passed is not None
    ):
        out.append(
            make_envelope(
                ProgressEvent(
                    kind="call.evaluated",
                    run_id=completed.run_id,
                    call_id=completed.call_id,
                    run_item_id=completed.run_item_id,
                    overall_score=completed.overall_score,
                    passed=completed.passed,
                    critical_failure=completed.critical_failure,
                ),
                producer=producer,
                correlation_id=env.correlation_id,
                causation_id=env.event_id,
                event_id=deterministic_event_id(env.event_id, EventType.PROGRESS),
            )
        )
    return out


class EvaluationReader(Protocol):
    """Read-only port used to rebuild the outputs of an already-processed ``call.completed``."""

    async def load_completed(self, call_id: uuid.UUID) -> EvaluationCompleted | None:
        """The ``evaluation.completed`` payload for the stored evaluation, or ``None``."""


async def reproduce_call_completed(
    env: Envelope[CallCompleted], reader: EvaluationReader, *, producer: str = "evaluator"
) -> list[AnyEnvelope]:
    """Duplicate delivery: no judge call, no write; re-emit the stored evaluation's events."""
    if env.payload.end_reason in UNEVALUABLE_END_REASONS:
        return []
    completed = await reader.load_completed(env.payload.call_id)
    return [] if completed is None else evaluation_outputs(env, completed, producer=producer)


# ---------------------------------------------------------------------------------------------
# finalizer
# ---------------------------------------------------------------------------------------------

TERMINAL_ITEM_STATUSES = frozenset(
    {"evaluated", "judge_error", "error", "cancelled", "skipped_budget"}
)


@dataclass(frozen=True)
class RunItemOutcome:
    """One ``run_items`` row joined with its evaluation (if any)."""

    status: str
    overall_score: float | None = None
    passed: bool | None = None
    critical_failure: bool = False
    needs_human_review: bool = False
    #: Regression runs: does a failure of this item fail the suite?
    blocking: bool = True
    #: Regression runs: the test's thresholds (FR-RG-2). Without them ``passed`` decides.
    baseline_score: float | None = None
    tolerance: float | None = None


@dataclass(frozen=True)
class RunState:
    run_id: uuid.UUID
    agent_id: uuid.UUID
    kind: RunKind
    #: ``test_runs.status`` (``cancelled`` once a cancel was requested).
    status: str
    items: Sequence[RunItemOutcome]


class FinalizerStore(Protocol):
    async def load_run_state(self, run_id: uuid.UUID) -> RunState | None: ...

    async def claim_run_completion(
        self, run_id: uuid.UUID, status: RunFinalStatus, summary: RunCompletedSummary
    ) -> bool:
        """Atomically store status + summary and set ``finished_at``; ``True`` only for the first
        caller (``UPDATE ... WHERE status IN ('queued','running') RETURNING id``)."""


def run_is_complete(state: RunState) -> bool:
    return bool(state.items) and all(i.status in TERMINAL_ITEM_STATUSES for i in state.items)


def item_passes_suite(item: RunItemOutcome) -> bool:
    """A regression item passes when it was evaluated and met its test's baseline - tolerance with
    no critical failure (FR-RG-2); an item without thresholds falls back to the judge's verdict."""
    if item.status != "evaluated":
        return False
    if item.baseline_score is None:
        return bool(item.passed)
    return regression_passed(
        item.overall_score,
        item.critical_failure,
        item.baseline_score,
        DEFAULT_TOLERANCE if item.tolerance is None else item.tolerance,
    )


def summarize_run(state: RunState) -> RunCompletedSummary:
    scored = [i for i in state.items if i.status == "evaluated" and i.overall_score is not None]
    passed = sum(1 for i in scored if i.passed)
    suite_passed: bool | None = None
    if state.kind == "regression":
        suite_passed = all(item_passes_suite(i) for i in state.items if i.blocking)
    return RunCompletedSummary(
        item_count=len(state.items),
        evaluated_count=len(scored),
        error_count=sum(1 for i in state.items if i.status in ("error", "judge_error")),
        pass_rate=(passed / len(scored)) if scored else None,
        critical_failures=sum(1 for i in scored if i.critical_failure),
        needs_review=sum(
            1 for i in state.items if i.needs_human_review or i.status == "judge_error"
        ),
        score_mean=(
            round(
                sum(i.overall_score for i in scored if i.overall_score is not None) / len(scored), 2
            )
            if scored
            else None
        ),
        suite_passed=suite_passed,
    )


def final_status(state: RunState) -> RunFinalStatus:
    if state.status == "cancelled" or any(i.status == "cancelled" for i in state.items):
        return "cancelled"
    evaluated = sum(1 for i in state.items if i.status == "evaluated")
    if evaluated == len(state.items):
        return "completed"
    return "partial" if evaluated else "failed"


def run_completed_event_id(run_id: uuid.UUID) -> uuid.UUID:
    """One id per run (not per input event), so any re-trigger produces the same event."""
    return uuid.uuid5(run_id, EventType.RUN_COMPLETED.value)


async def handle_evaluation_completed(
    env: Envelope[EvaluationCompleted],
    store: FinalizerStore,
    *,
    producer: str = "finalizer",
) -> list[AnyEnvelope]:
    """``evaluation.completed`` -> when every item of the run is terminal, emit ``run.completed``
    exactly once (guarded by ``claim_run_completion``)."""
    run_id = env.payload.run_id
    if run_id is None:  # uploaded / imported call, not part of a run
        return []
    state = await store.load_run_state(run_id)
    if state is None or not run_is_complete(state):
        return []
    status = final_status(state)
    summary = summarize_run(state)
    if not await store.claim_run_completion(run_id, status, summary):
        return []
    return run_completed_outputs(
        env.event_id, run_id, state.agent_id, state.kind, status, summary, producer=producer
    )


def run_completed_outputs(
    causation_id: uuid.UUID | None,
    run_id: uuid.UUID,
    agent_id: uuid.UUID,
    kind: RunKind,
    status: RunFinalStatus,
    summary: RunCompletedSummary,
    *,
    producer: str = "finalizer",
) -> list[AnyEnvelope]:
    """``run.completed`` and its progress event. Their ids derive from the run, not from the
    input event, so every path that emits them (first completion or a re-delivery) agrees."""
    completed = RunCompleted(
        run_id=run_id, agent_id=agent_id, kind=kind, status=status, summary=summary
    )
    progress = ProgressEvent(
        kind="run.completed",
        run_id=run_id,
        pass_rate=summary.pass_rate,
        critical_failures=summary.critical_failures,
    )
    return [
        make_envelope(
            completed,
            producer=producer,
            correlation_id=str(run_id),
            causation_id=causation_id,
            event_id=run_completed_event_id(run_id),
        ),
        make_envelope(
            progress,
            producer=producer,
            correlation_id=str(run_id),
            causation_id=causation_id,
            event_id=uuid.uuid5(run_id, "progress:run.completed"),
        ),
    ]


@dataclass(frozen=True)
class FinishedRun:
    """A run whose completion was already claimed (``test_runs.finished_at`` is set)."""

    agent_id: uuid.UUID
    kind: RunKind
    status: RunFinalStatus
    summary: RunCompletedSummary


class RunReader(Protocol):
    async def load_finished_run(self, run_id: uuid.UUID) -> FinishedRun | None: ...


async def reproduce_run_completed(
    env: Envelope[EvaluationCompleted], reader: RunReader, *, producer: str = "finalizer"
) -> list[AnyEnvelope]:
    """Duplicate delivery: if the run is already finished, emit its (deterministic-id)
    ``run.completed`` again in case the first attempt died before producing it."""
    run_id = env.payload.run_id
    if run_id is None:
        return []
    finished = await reader.load_finished_run(run_id)
    if finished is None:
        return []
    return run_completed_outputs(
        env.event_id,
        run_id,
        finished.agent_id,
        finished.kind,
        finished.status,
        finished.summary,
        producer=producer,
    )


__all__ = [
    "CallNotFoundError",
    "EvaluationReader",
    "EvaluatorStore",
    "FinalizerStore",
    "FinishedRun",
    "RunItemOutcome",
    "RunReader",
    "RunState",
    "handle_call_completed",
    "handle_evaluation_completed",
    "reproduce_call_completed",
    "reproduce_run_completed",
    "summarize_run",
]
