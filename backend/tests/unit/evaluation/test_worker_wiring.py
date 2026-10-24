"""Unit tests for the evaluator / finalizer worker wiring (no Kafka, no Postgres).

The exactly-once behaviour against real Kafka and Postgres is in
``tests/integration/test_evaluator_exactly_once.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from pareeksha.evaluation.handlers import (
    CallNotFoundError,
    FinishedRun,
    handle_call_completed,
    reproduce_call_completed,
    reproduce_run_completed,
)
from pareeksha.evaluation.pg_stores import RubricNotFoundError, expected_amounts_from_fixtures
from pareeksha.events.consumer import REGISTRY, Ctx, PermanentError, RetryableError, classify
from pareeksha.events.schemas import (
    CallCompleted,
    EvaluationCompleted,
    RunCompletedSummary,
    make_envelope,
)
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import ConsumerGroups, Topics
from pareeksha.llm.base import (
    LLMPermanentError,
    LLMProviderName,
    LLMPurpose,
    LLMRetryableError,
)
from pareeksha.llm.client import UsageRecord
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.workers import _outgoing, evaluator, finalizer
from tests.fixtures import synthetic_calls as sc
from tests.unit.evaluation.fakes import FakeEvaluatorStore, ScriptedProvider, client_for, judge_json

RUN = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
AGENT = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ITEM = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


def call_env(end_reason: str = "goal_achieved") -> Any:
    payload = CallCompleted(
        call_id=sc.CALL_ID_CLEAN,
        source="simulation",
        agent_id=AGENT,
        run_id=RUN,
        run_item_id=ITEM,
        end_reason=end_reason,  # type: ignore[arg-type]
    )
    return make_envelope(payload, producer="t", correlation_id=str(RUN))


def evaluation_env(run_id: uuid.UUID | None = RUN) -> Any:
    payload = EvaluationCompleted(
        call_id=sc.CALL_ID_CLEAN,
        evaluation_id=uuid.uuid4(),
        run_id=run_id,
        agent_id=AGENT,
        overall_score=90,
        passed=True,
    )
    return make_envelope(payload, producer="t", correlation_id="c")


def test_workers_are_registered_with_the_consumer_framework() -> None:
    ev = REGISTRY[str(ConsumerGroups.EVALUATOR)]
    assert ev.topics == (Topics.CALL_COMPLETED,)
    assert ev.handler is evaluator.on_call_completed and ev.reproduce is evaluator.reproduce
    fin = REGISTRY[str(ConsumerGroups.FINALIZER)]
    assert fin.topics == (Topics.EVALUATION_COMPLETED,)
    assert fin.handler is finalizer.on_evaluation_completed
    assert fin.reproduce is finalizer.reproduce


def test_expected_amounts_come_from_numeric_amount_fixtures_only() -> None:
    fixtures = {"emi_amount": 4200, "amount": 1.5, "due_date": "Friday", "flag_amount": True}
    assert expected_amounts_from_fixtures(fixtures) == {"emi_amount": 4200, "amount": 1.5}


class Reader:
    def __init__(self, completed: EvaluationCompleted | None) -> None:
        self.completed = completed

    async def load_completed(self, call_id: uuid.UUID) -> EvaluationCompleted | None:
        return self.completed


async def test_reproduced_outputs_match_the_original_ones() -> None:
    env = call_env()
    store = FakeEvaluatorStore(sc.clean_call())
    first = await handle_call_completed(env, store, client_for(ScriptedProvider([judge_json()])))
    stored = first[0].payload
    assert isinstance(stored, EvaluationCompleted)
    again = await reproduce_call_completed(env, Reader(stored))
    assert [(e.event_id, e.type) for e in again] == [(e.event_id, e.type) for e in first]
    assert again[0].payload == stored


async def test_reproduce_without_a_stored_evaluation_or_for_unevaluable_calls_is_empty() -> None:
    assert await reproduce_call_completed(call_env(), Reader(None)) == []
    assert await reproduce_call_completed(call_env("infra_error"), Reader(None)) == []


class RunReaderFake:
    def __init__(self, finished: FinishedRun | None) -> None:
        self.finished = finished

    async def load_finished_run(self, run_id: uuid.UUID) -> FinishedRun | None:
        return self.finished


async def test_reproduce_run_completed_uses_the_run_derived_ids() -> None:
    summary = RunCompletedSummary(item_count=1, evaluated_count=1, error_count=0, pass_rate=1.0)
    finished = FinishedRun(agent_id=AGENT, kind="matrix", status="completed", summary=summary)
    out = await reproduce_run_completed(evaluation_env(), RunReaderFake(finished))
    assert out[0].event_id == uuid.uuid5(RUN, "run.completed")
    assert out[1].event_id == uuid.uuid5(RUN, "progress:run.completed")
    assert await reproduce_run_completed(evaluation_env(), RunReaderFake(None)) == []
    assert await reproduce_run_completed(evaluation_env(None), RunReaderFake(finished)) == []


def test_to_outgoing_keeps_ids_and_correlation() -> None:
    env = call_env()
    (out,) = _outgoing.to_outgoing([env])
    assert out.event_id == env.event_id and out.correlation_id == env.correlation_id
    assert out.payload is env.payload


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (LLMPermanentError("bad key"), PermanentError),
        (LLMRetryableError("429"), RetryableError),
        (CallNotFoundError("gone"), PermanentError),
        (RubricNotFoundError("no rubric"), RetryableError),
    ],
)
async def test_handler_maps_failures_onto_framework_dispositions(
    monkeypatch: pytest.MonkeyPatch, raised: Exception, expected: type[Exception]
) -> None:
    async def boom(*_: Any, **__: Any) -> None:
        raise raised

    class Sink:
        def scope(self, **_: Any) -> Any:
            import contextlib

            return contextlib.nullcontext()

    monkeypatch.setattr(evaluator, "handle_call_completed", boom)
    evaluator.set_client(client_for(ScriptedProvider([])), Sink())  # type: ignore[arg-type]
    try:
        with pytest.raises(expected) as info:
            await evaluator.on_call_completed(call_env(), Ctx(None, "g", "t", 0, 0, 1))  # type: ignore[arg-type]
    finally:
        evaluator.set_client(None)
    assert info.type is expected
    classify(info.value)


def test_get_client_builds_the_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    evaluator.set_client(None)
    try:
        client, usage = evaluator.get_client()
        assert client.settings.llm_provider is LLMProviderName.DEEPSEEK
        assert evaluator.get_client() == (client, usage)
    finally:
        evaluator.set_client(None)


async def test_usage_sink_never_fails_the_evaluation_when_the_insert_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = ApiUsageSink(EventSettings("localhost:9", "postgresql://u:p@127.0.0.1:1/none"))
    record = UsageRecord(
        provider=LLMProviderName.DEEPSEEK,
        model="m",
        purpose=LLMPurpose.JUDGE,
        input_tokens=10,
        output_tokens=5,
    )
    with sink.scope(run_id=RUN, call_id=sc.CALL_ID_CLEAN):
        await sink(record)  # connection refused: logged, not raised
    assert "api_usage insert failed" in caplog.text
    await sink.close()
