"""Quick tests ("Test my prompt") and the in-app assistant."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from pareeksha.api.auth import Principal, ReadKey, WriteKey
from pareeksha.api.deps import AUTH_ERRORS, Db, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.llm_deps import ClientBuilder, LlmBuilder, usage_sink
from pareeksha.api.ratelimit import ASSISTANT_LIMIT, QUICK_TEST_LIMIT
from pareeksha.db.session import SessionFactory, get_session_factory
from pareeksha.llm._http import public_error
from pareeksha.llm.base import LLMError
from pareeksha.llm.client import JSONGenerationError, LLMClient
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.llm.project_settings import effective_llm_settings
from pareeksha.quicktest import assistant, service
from pareeksha.regression.estimate import remaining_budget
from pareeksha.schemas.quick_tests import (
    AssistantRequest,
    AssistantResponse,
    ImproveRequest,
    QuickTestCreate,
    QuickTestCreated,
    QuickTestImprovement,
    QuickTestListItem,
    QuickTestOut,
    QuickTestSetup,
)

router = APIRouter(tags=["quick-tests"], responses=AUTH_ERRORS)
Factory = Annotated[SessionFactory, Depends(get_session_factory)]


async def _budget_left(session: Db, key: Principal) -> None:
    """402 when the project's budget is used up."""
    remaining = await remaining_budget(session, key.project_id)
    if remaining is not None and remaining <= 0:
        raise ApiError(
            402,
            "budget_exceeded",
            "The project's budget is used up",
            {"remaining_budget": remaining},
        )


@asynccontextmanager
async def _llm(
    session: Db, key: Principal, build: ClientBuilder, factory: SessionFactory
) -> AsyncIterator[tuple[LLMSettings, LLMClient]]:
    """The project's LLM settings and client; provider failures become 422 / 502 errors."""
    try:
        settings = await effective_llm_settings(session, key.project_id)
        client = build(settings, usage_sink(factory, key.project_id))
    except LLMConfigError as exc:
        raise ApiError(422, "llm_not_configured", str(exc)) from exc
    secret = settings.deepseek_api_key or settings.gemini_api_key
    try:
        yield settings, client
    except JSONGenerationError as exc:
        raise ApiError(
            502,
            "invalid_output",
            "The AI model did not return a usable answer, even after a retry; try again.",
        ) from exc
    except LLMConfigError as exc:
        raise ApiError(422, "llm_not_configured", str(exc)) from exc
    except LLMError as exc:
        raise ApiError(502, "upstream_error", public_error(exc, secret)) from exc
    finally:
        await client.aclose()


@router.get("/quick-tests/setup", summary="What the Test my prompt screen needs")
async def quick_test_setup(key: ReadKey, session: Db) -> QuickTestSetup:
    """Whether an AI key is set, the model the bot runs on, the cost limit, the documents."""
    settings = await effective_llm_settings(session, key.project_id)
    provider, model, _, _ = service.agent_model(settings)
    return QuickTestSetup(
        llm_ready=service.llm_ready(settings),
        llm_provider=provider,
        agent_model=model,
        auto_run_limit=service.auto_run_limit(),
        knowledge_bases=await service.setup_kbs(session, key.project_id),
    )


@router.post(
    "/quick-tests",
    status_code=201,
    responses=errors(402, 404, 409, 422, 429, 502),
    summary="Test a system prompt: find its rules, write conversations, run them",
)
async def create_quick_test(
    body: QuickTestCreate, key: WriteKey, session: Db, build: LlmBuilder, factory: Factory
) -> QuickTestCreated:
    """402 ``confirm_cost`` (details: ``estimate`` and ``plan``) above the auto-run limit: send
    the same body again with ``confirm_cost: true`` and that ``plan``."""
    QUICK_TEST_LIMIT.check(key.key_id)  # a confirmed plan still creates a paid run
    await _budget_left(session, key)
    async with _llm(session, key, build, factory) as (settings, client):
        return await service.create_quick_test(session, key, settings, client, body)


@router.get("/quick-tests", summary="The newest prompt tests")
async def list_quick_tests(
    key: ReadKey, session: Db, build: LlmBuilder, factory: Factory
) -> list[QuickTestListItem]:
    """The project's 20 newest prompt tests with their rule counts; tests that are still
    checking get a batch of checks, so lists alone also move them forward."""
    items = await service.list_tests(session, key.project_id)
    waiting = [t.id for t in items if t.status == "checking"][:3]
    remaining = await remaining_budget(session, key.project_id) if waiting else None
    if waiting and (remaining is None or remaining > 0):
        try:
            async with _llm(session, key, build, factory) as (_, client):
                for test_id in waiting:
                    await service.check_finished_calls(session, key.project_id, test_id, client)
        except ApiError:
            pass  # tried again on the next read
        items = await service.list_tests(session, key.project_id)
    return items


@router.get(
    "/quick-tests/{test_id}",
    responses=errors(404),
    summary="A prompt test with its rule results (checks finished conversations as it reads)",
)
async def get_quick_test(
    test_id: UUID, key: ReadKey, session: Db, build: LlmBuilder, factory: Factory
) -> QuickTestOut:
    """The test as the page shows it; finished conversations are checked on the way."""
    row = await service.require_row(session, key.project_id, test_id)
    remaining = await remaining_budget(session, key.project_id)
    if remaining is None or remaining > 0:
        try:
            async with _llm(session, key, build, factory) as (_, client):
                await service.check_finished_calls(session, key.project_id, test_id, client)
        except ApiError:
            pass  # checking is retried on the next read; the page still shows the progress
    await session.refresh(row)
    return await service.build_out(session, row)


@router.post(
    "/quick-tests/{test_id}/improve",
    responses=errors(402, 404, 409, 422, 429, 502),
    summary="Rewrite the prompt from the test's results; optionally test the rewrite",
)
async def improve_quick_test(
    test_id: UUID,
    body: ImproveRequest,
    key: WriteKey,
    session: Db,
    build: LlmBuilder,
    factory: Factory,
) -> QuickTestImprovement:
    """Rewrite the prompt from the results, and with ``retest`` test the rewrite."""
    QUICK_TEST_LIMIT.check(key.key_id)
    await _budget_left(session, key)
    row = await service.require_row(session, key.project_id, test_id)
    async with _llm(session, key, build, factory) as (settings, client):
        improvement = await service.improve(session, client, row, body.instructions)
        if body.retest:
            created = await service.retest(session, key, settings, row, improvement.improved_prompt)
            improvement.retest_id = created.id
            row.improvement = improvement.model_dump(mode="json")
            await session.flush()
        return improvement


@router.post(
    "/quick-tests/{test_id}/retest",
    status_code=201,
    responses=errors(402, 404, 409, 422),
    summary="Test the test's suggested prompt on the same conversations",
)
async def retest_quick_test(
    test_id: UUID, key: WriteKey, session: Db, confirm_cost: bool = False
) -> QuickTestCreated:
    """Test the stored improved prompt on the same conversations (409 without one)."""
    await _budget_left(session, key)
    row = await service.require_row(session, key.project_id, test_id)
    if not row.improvement:
        raise ApiError(409, "no_improvement", "Ask for an improvement first")
    settings = await effective_llm_settings(session, key.project_id)
    prompt = str(row.improvement["improved_prompt"])
    created = await service.retest(session, key, settings, row, prompt, confirm_cost=confirm_cost)
    row.improvement = {**row.improvement, "retest_id": str(created.id)}
    await session.flush()
    return created


@router.post(
    "/assistant/chat",
    responses=errors(402, 422, 429, 502),
    summary="One turn with the in-app assistant (stateless: send the whole history)",
)
async def assistant_chat(
    body: AssistantRequest, key: WriteKey, session: Db, build: LlmBuilder, factory: Factory
) -> AssistantResponse:
    """One assistant turn; it may start a test, improve one or name a page to open."""
    ASSISTANT_LIMIT.check(key.key_id)
    await _budget_left(session, key)
    async with _llm(session, key, build, factory) as (settings, client):
        return await assistant.chat(session, key, settings, client, body)
