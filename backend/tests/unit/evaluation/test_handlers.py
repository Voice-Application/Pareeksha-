from __future__ import annotations

import uuid
from typing import cast

import pytest

from pareeksha.evaluation.evaluator import evaluation_id
from pareeksha.evaluation.handlers import (
    CallNotFoundError,
    RunItemOutcome,
    RunState,
    final_status,
    handle_call_completed,
    handle_evaluation_completed,
    run_completed_event_id,
    run_is_complete,
    summarize_run,
)
from pareeksha.events.schemas import (
    CallCompleted,
    EndReason,
    EvaluationCompleted,
    EventType,
    ProgressEvent,
    RunCompleted,
    RunKind,
    deterministic_event_id,
    make_envelope,
    parse_envelope,
)
from tests.fixtures import synthetic_calls as sc
from tests.unit.evaluation.fakes import (
    FakeEvaluatorStore,
    FakeFinalizerStore,
    ScriptedProvider,
    client_for,
    judge_json,
)

RUN = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
AGENT = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ITEM = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def call_completed_env(end_reason: str | None = "goal_achieved"):  # type: ignore[no-untyped-def]
    payload = CallCompleted(
        call_id=sc.CALL_ID_CLEAN,
        source="simulation",
        agent_id=AGENT,
        run_id=RUN,
        run_item_id=ITEM,
        end_reason=cast(EndReason, end_reason),
    )
    return make_envelope(payload, producer="simulator@t", correlation_id=str(RUN))


async def test_evaluator_emits_contract_valid_events_with_deterministic_ids() -> None:
    env = call_completed_env()
    store = FakeEvaluatorStore(sc.clean_call())
    provider = ScriptedProvider([judge_json(evidence=[2])])
    out = await handle_call_completed(env, store, client_for(provider))
    assert len(store.saved) == 1 and store.saved[0].id == evaluation_id(sc.CALL_ID_CLEAN)
    done, progress = out
    assert done.event_id == deterministic_event_id(env.event_id, EventType.EVALUATION_COMPLETED)
    assert done.causation_id == str(env.event_id) and done.topic.value.endswith(
        "evaluation.completed.v1"
    )
    p = done.payload
    assert isinstance(p, EvaluationCompleted)
    assert (p.status, p.passed, p.overall_score, p.run_id, p.run_item_id) == (
        "ok",
        True,
        100.0,
        RUN,
        ITEM,
    )
    assert isinstance(progress.payload, ProgressEvent) and progress.payload.kind == "call.evaluated"
    for e in out:  # round-trips through the frozen contract
        assert parse_envelope(e.to_json_bytes()).event_id == e.event_id


async def test_redelivery_reproduces_the_same_output_event_ids() -> None:
    env = call_completed_env()
    ids = []
    for _ in range(2):
        store = FakeEvaluatorStore(sc.clean_call())
        out = await handle_call_completed(
            env,
            store,
            client_for(ScriptedProvider([judge_json(evidence=[2])])),
        )
        ids.append([e.event_id for e in out])
    assert ids[0] == ids[1]


async def test_judge_error_emits_evaluation_completed_without_score_and_no_progress() -> None:
    store = FakeEvaluatorStore(sc.clean_call())
    provider = ScriptedProvider([judge_json(evidence=[99]), judge_json(evidence=[99]), judge_json(evidence=[99])])
    out = await handle_call_completed(call_completed_env(), store, client_for(provider))
    assert len(out) == 1
    p = out[0].payload
    assert isinstance(p, EvaluationCompleted)
    assert p.status == "judge_error" and p.overall_score is None and p.needs_human_review


@pytest.mark.parametrize("reason", ["connect_failed", "infra_error", "cancelled"])
async def test_unevaluable_calls_are_skipped(reason: str) -> None:
    store = FakeEvaluatorStore(sc.clean_call())
    provider = ScriptedProvider([])
    out = await handle_call_completed(call_completed_env(reason), store, client_for(provider))
    assert out == [] and not provider.requests and not store.saved


async def test_missing_call_is_a_permanent_error() -> None:
    with pytest.raises(CallNotFoundError):
        await handle_call_completed(
            call_completed_env(),
            FakeEvaluatorStore(None),
            client_for(ScriptedProvider([])),
        )


# -- finalizer --------------------------------------------------------------------------------


def item(status: str = "evaluated", score: float | None = 90.0, passed: bool | None = True, **kw):  # type: ignore[no-untyped-def]
    return RunItemOutcome(status, score if status == "evaluated" else None, passed, **kw)


def state(items: list[RunItemOutcome], kind: str = "matrix", status: str = "running") -> RunState:
    return RunState(RUN, AGENT, cast(RunKind, kind), status, items)


def eval_env(run_id: uuid.UUID | None = RUN):  # type: ignore[no-untyped-def]
    payload = EvaluationCompleted(
        call_id=sc.CALL_ID_CLEAN,
        evaluation_id=uuid.uuid4(),
        run_id=run_id,
        overall_score=90.0,
        passed=True,
    )
    return make_envelope(payload, producer="evaluator@t", correlation_id=str(sc.CALL_ID_CLEAN))


def test_summary_numbers() -> None:
    s = state(
        [
            item(score=100.0),
            item(score=40.0, passed=False, critical_failure=True, needs_human_review=True),
            item("judge_error", needs_human_review=True),
            item("error"),
        ]
    )
    sm = summarize_run(s)
    assert (sm.item_count, sm.evaluated_count, sm.error_count) == (4, 2, 2)
    assert sm.pass_rate == 0.5 and sm.score_mean == 70.0
    assert sm.critical_failures == 1 and sm.needs_review == 2 and sm.suite_passed is None


def test_summary_with_no_scored_items() -> None:
    sm = summarize_run(state([item("error")]))
    assert sm.pass_rate is None and sm.score_mean is None and sm.evaluated_count == 0


def test_regression_suite_passed_only_if_every_blocking_item_passes() -> None:
    ok = state([item(), item(score=50.0, passed=False, blocking=False)], kind="regression")
    assert summarize_run(ok).suite_passed is True
    bad = state([item(), item(score=50.0, passed=False)], kind="regression")
    assert summarize_run(bad).suite_passed is False
    errored = state([item(), item("error")], kind="regression")
    assert summarize_run(errored).suite_passed is False


def test_final_status_rules() -> None:
    assert final_status(state([item(), item()])) == "completed"
    assert final_status(state([item(), item("error")])) == "partial"
    assert final_status(state([item("error"), item("judge_error")])) == "failed"
    assert final_status(state([item(), item()], status="cancelled")) == "cancelled"
    assert final_status(state([item(), item("cancelled")])) == "cancelled"


def test_run_is_complete_requires_all_terminal() -> None:
    assert run_is_complete(state([item(), item("error"), item("skipped_budget")]))
    assert not run_is_complete(state([item(), item("evaluating")]))
    assert not run_is_complete(state([]))


async def test_finalizer_waits_until_all_items_are_terminal() -> None:
    store = FakeFinalizerStore(state([item(), item("evaluating")]))
    assert await handle_evaluation_completed(eval_env(), store) == []
    assert not store.claimed


async def test_finalizer_emits_run_completed_exactly_once() -> None:
    store = FakeFinalizerStore(state([item(), item(score=70.0, passed=False)]))
    first = await handle_evaluation_completed(eval_env(), store)
    second = await handle_evaluation_completed(eval_env(), store)  # another item's event
    assert second == [] and len(store.claims) == 1
    done, progress = first
    assert done.event_id == run_completed_event_id(RUN)
    p = done.payload
    assert isinstance(p, RunCompleted) and p.status == "completed" and p.agent_id == AGENT
    assert p.summary.pass_rate == 0.5 and p.summary.score_mean == 80.0
    assert isinstance(progress.payload, ProgressEvent) and progress.payload.kind == "run.completed"
    assert progress.payload.pass_rate == 0.5
    assert parse_envelope(done.to_json_bytes()).event_id == done.event_id


async def test_finalizer_ignores_calls_outside_runs_and_unknown_runs() -> None:
    assert await handle_evaluation_completed(eval_env(None), FakeFinalizerStore(None)) == []
    assert await handle_evaluation_completed(eval_env(), FakeFinalizerStore(None)) == []
