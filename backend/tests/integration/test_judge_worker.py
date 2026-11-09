"""The ``judge`` worker against real Postgres: it judges finished quick-test calls without a reader.

A quick test's verdicts are normally filled when its result page is read. This proves the background
worker drives the same ``check_finished_calls`` across tests with finished-but-unchecked calls, so a
test nobody opens still gets judged, and a test with nothing left to judge is left untouched.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.llm_deps import get_client_builder
from pareeksha.api.main import app
from pareeksha.api.ratelimit import ASSISTANT_LIMIT, QUICK_TEST_LIMIT
from pareeksha.db.models import QuickTests
from pareeksha.llm.base import JSONCompletionRequest, JSONCompletionResult, LLMUsage
from pareeksha.llm.client import LLMClient
from pareeksha.workers.judge import JudgeWorker, _candidates
from tests.conftest import Tenant
from tests.integration.test_quick_tests import (
    _create,
    _finish_calls,
    _library,
    verdicts,
)
from tests.unit.api_fakes import ScriptedProvider


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[ScriptedProvider]:
    """A scripted LLM for every route, the platform DeepSeek key, and no cost-limit surprises.

    Mirrors ``test_quick_tests.provider`` so the worker and the API share one judge provider.
    """
    monkeypatch.chdir(tmp_path)  # no .env
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-platform")
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())
    for name in (
        "LLM_PROVIDER",
        "COST_DEEPSEEK_PER_1K_INPUT_TOKENS",
        "COST_DEEPSEEK_PER_1K_OUTPUT_TOKENS",
        "BUDGET_CREDITS",
        "QUICK_TEST_COST_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)
    fake = ScriptedProvider()
    app.dependency_overrides[get_client_builder] = lambda: (
        lambda settings, sink: LLMClient(fake, settings, usage_sink=sink)
    )
    ASSISTANT_LIMIT._state.clear()
    QUICK_TEST_LIMIT._state.clear()
    yield fake
    app.dependency_overrides.pop(get_client_builder, None)


def _worker(factory: async_sessionmaker[AsyncSession], provider: ScriptedProvider) -> JudgeWorker:
    """A worker that builds its judge client from the scripted provider (no real network)."""
    return JudgeWorker(
        factory,
        build=lambda settings, sink: LLMClient(provider, settings, usage_sink=sink),
    )


def _judge(provider: ScriptedProvider) -> Any:
    """A judge that answers each request from its transcript (calls run in parallel)."""

    async def judge(request: JSONCompletionRequest) -> JSONCompletionResult:
        """Return a broken verdict when the leaking agent turn is in the transcript, else kept."""
        provider.requests.append(request)
        leaked = "| agent | Your balance is Rs 4,850" in request.messages[0].content
        return JSONCompletionResult(
            provider=provider.name,
            model=request.model,
            text=verdicts(leaked),
            usage=LLMUsage(input_tokens=10, output_tokens=10),
            latency_ms=1,
        )

    return judge


async def test_the_worker_judges_finished_calls_without_a_reader(
    api: AsyncClient,
    tenant: Tenant,
    provider: ScriptedProvider,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One tick fills a never-read test's verdicts; a second tick finds nothing left to judge."""
    await _library(api, tenant)
    created = await _create(api, tenant, provider)
    calls = await _finish_calls(
        session_factory,
        created["id"],
        ["Your balance is Rs 4,850", "Please tell me your DOB first.", "Please share your DOB."],
    )
    monkeypatch.setattr(provider, "complete_json", _judge(provider))

    # the page was never opened, so nothing is judged yet
    async with session_factory() as s:
        row = await s.get(QuickTests, uuid.UUID(created["id"]))
        assert row is not None and row.verdicts == {}

    worker = _worker(session_factory, provider)
    claimed = await worker.run_once()
    assert claimed == 1 and worker.judged_tests == 1

    async with session_factory() as s:
        row = await s.get(QuickTests, uuid.UUID(created["id"]))
        assert row is not None
        assert {str(c) for c in calls} == set(row.verdicts)  # every finished call judged
        balance = next(
            v for vs in row.verdicts.values() for v in vs if v["rule_id"] == "no_balance_before_dob"
        )
        assert balance["verdict"] in ("broken", "kept")

    # the leaking call was judged broken, the others kept
    leaked = row.verdicts[str(calls[0])]
    assert any(v["rule_id"] == "no_balance_before_dob" and v["verdict"] == "broken" for v in leaked)

    asked = len(provider.requests)
    second = await worker.run_once()
    assert second == 0  # nothing finished-but-unchecked remains
    assert len(provider.requests) == asked  # nothing is judged twice


async def test_a_test_with_no_unchecked_calls_is_not_a_candidate(
    api: AsyncClient,
    tenant: Tenant,
    provider: ScriptedProvider,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A test whose finished calls are already judged is left alone (not re-claimed, re-judged)."""
    await _library(api, tenant)
    created = await _create(api, tenant, provider)
    await _finish_calls(
        session_factory,
        created["id"],
        ["Please share your DOB.", "Please share your DOB.", "Please share your DOB."],
    )
    monkeypatch.setattr(provider, "complete_json", _judge(provider))

    worker = _worker(session_factory, provider)
    assert await worker.run_once() == 1

    async with session_factory() as s:
        candidates = await _candidates(s, limit=20)
        await s.rollback()
    assert candidates == []  # everything is checked: no work left to claim


async def test_a_test_with_no_finished_calls_is_not_a_candidate(
    api: AsyncClient,
    tenant: Tenant,
    provider: ScriptedProvider,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A still-running test (no completed calls) offers the worker nothing to do."""
    await _library(api, tenant)
    created = await _create(api, tenant, provider)

    async with session_factory() as s:
        candidates = await _candidates(s, limit=20)
        await s.rollback()
    assert candidates == []
    assert created["id"]  # the test exists; it simply has no finished calls yet
