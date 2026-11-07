"""The per-project LLM settings resolver and the provider cache the workers use."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import httpx
import pytest

from pareeksha.db.models import ProjectLlmSettings
from pareeksha.integrations import ssrf
from pareeksha.integrations.crypto import SecretBox
from pareeksha.llm import deepseek
from pareeksha.llm.base import (
    ChatMessage,
    JSONCompletionRequest,
    LLMPermanentError,
    LLMProviderName,
    LLMPurpose,
)
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.llm.deepseek import DeepSeekProvider
from pareeksha.llm.factory import build_provider
from pareeksha.llm.gemini import GeminiProvider
from pareeksha.llm.project_settings import (
    OPENAI_COMPATIBLE,
    ProjectLLMClients,
    ProjectLLMRow,
    apply_row,
    effective_llm_settings,
)
from tests.unit.api_fakes import FakeSession, clean_llm_env

PID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    clean_llm_env(monkeypatch, tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-deepseek")


def row(provider: str = "deepseek", key: str | None = None, **kw: Any) -> ProjectLLMRow:
    token = SecretBox(os.environ["SECRET_KEY"]).encrypt({"api_key": key}) if key else None
    fields: dict[str, Any] = {
        "provider": provider,
        "base_url": None,
        "judge_model": None,
        "caller_model": None,
        "designer_model": None,
        "api_key_encrypted": token,
        "api_key_last4": key[-4:] if key else None,
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    return ProjectLLMRow(**{**fields, **kw})


def stored(session: FakeSession, r: ProjectLLMRow) -> None:
    session.rows[(ProjectLlmSettings, PID)] = ProjectLlmSettings(project_id=PID, **vars(r))


def test_designer_model_defaults_to_the_judge_model(monkeypatch: pytest.MonkeyPatch) -> None:
    s = LLMSettings(_env_file=None)
    assert s.designer_model == s.judge_model == s.model_for(LLMPurpose.DESIGNER)
    assert s.temperature_for(LLMPurpose.DESIGNER) == pytest.approx(0.2)
    monkeypatch.setenv("DEEPSEEK_DESIGNER_MODEL", "d-model")
    assert LLMSettings(_env_file=None).model_for(LLMPurpose.DESIGNER) == "d-model"


def test_no_row_is_the_environment() -> None:
    env = LLMSettings()
    assert apply_row(env, None) is env


async def test_effective_settings_without_a_row_come_from_the_environment() -> None:
    s = await effective_llm_settings(FakeSession(), PID)
    assert s.llm_provider is LLMProviderName.DEEPSEEK and s.api_key == "env-deepseek"


def test_deepseek_row_overrides_models_and_key() -> None:
    s = apply_row(LLMSettings(), row(key="own-key", judge_model="j", designer_model="d"))
    assert s.api_key == "own-key"
    assert s.judge_model == "j" and s.designer_model == "d"
    assert s.caller_model == LLMSettings().caller_model  # untouched: environment value
    assert s.deepseek_base_url == LLMSettings().deepseek_base_url


def test_deepseek_row_without_a_key_uses_the_environment_key() -> None:
    assert apply_row(LLMSettings(), row()).api_key == "env-deepseek"


def test_gemini_row() -> None:
    s = apply_row(LLMSettings(), row("gemini", key="g-key", judge_model="gj", caller_model="gc"))
    assert s.llm_provider is LLMProviderName.GEMINI
    assert (s.api_key, s.judge_model, s.caller_model, s.designer_model) == (
        "g-key",
        "gj",
        "gc",
        "gj",
    )


def test_openai_compatible_row_uses_the_user_url_and_never_the_environment_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_DESIGNER_MODEL", "env-designer")
    monkeypatch.setenv("COST_DEEPSEEK_PER_1K_INPUT_TOKENS", "1")
    r = row(
        OPENAI_COMPATIBLE, base_url="https://llm.example.com/v1", judge_model="j", caller_model="c"
    )
    s = apply_row(LLMSettings(), r)
    assert s.llm_provider is LLMProviderName.DEEPSEEK  # the OpenAI-compatible provider class
    assert s.deepseek_base_url == "https://llm.example.com/v1"
    assert s.deepseek_api_key is None
    with pytest.raises(LLMConfigError):
        _ = s.api_key  # env-deepseek is not sent to a foreign URL
    assert s.designer_model == "j"  # not the environment's DeepSeek designer model
    assert s.cost_deepseek_per_1k_input_tokens is None
    own = row(
        OPENAI_COMPATIBLE,
        key="k",
        base_url="https://llm.example.com/v1",
        judge_model="j",
        caller_model="c",
    )
    assert apply_row(LLMSettings(), own).api_key == "k"


def test_unreadable_stored_key_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    r = row(key="own-key")
    monkeypatch.setenv("SECRET_KEY", "ZmFrZS1rZXktZmFrZS1rZXktZmFrZS1rZXktZmFrZS0=")
    with pytest.raises(LLMConfigError):
        apply_row(LLMSettings(), r)


async def test_cache_reuses_until_the_row_changes() -> None:
    session, cache = FakeSession(), ProjectLLMClients()
    assert await cache.resolve(session, PID) is None  # no row: the caller keeps its own client

    stored(session, row(key="key-one"))
    first = await cache.resolve(session, PID)
    assert first is not None and isinstance(first.provider, DeepSeekProvider)
    assert await cache.resolve(session, PID) is first  # same settings: same provider

    stored(session, row(key="key-two", updated_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(1)))
    second = await cache.resolve(session, PID)  # a settings change applies without a restart
    assert second is not None
    assert second is not first and second.settings.api_key == "key-two"
    assert first.fingerprint != second.fingerprint

    stored(session, row("gemini", key="g", judge_model="a", caller_model="b"))
    third = await cache.resolve(session, PID)
    assert third is not None and isinstance(third.provider, GeminiProvider)

    session.rows.clear()  # DELETE /settings/llm: back to the environment
    assert await cache.resolve(session, PID) is None
    await cache.aclose()


async def test_cached_client_keeps_the_usage_sink_of_its_caller() -> None:
    session, cache = FakeSession(), ProjectLLMClients()
    stored(session, row(key="key-one"))
    resolved = await cache.resolve(session, PID)
    assert resolved is not None
    seen: list[Any] = []
    sink = seen.append
    a, b = resolved.client(sink), resolved.client()
    assert a.provider is b.provider is resolved.provider
    assert a._sink is sink and b._sink is None
    await cache.aclose()


async def test_cache_without_any_key_raises_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    session = FakeSession()
    stored(session, row())
    with pytest.raises(LLMConfigError):
        await ProjectLLMClients().resolve(session, PID)


# ---- SSRF guard for project-supplied base URLs


def _request() -> JSONCompletionRequest:
    return JSONCompletionRequest(
        purpose=LLMPurpose.JUDGE, model="m", messages=[ChatMessage(role="user", content="json")]
    )


def _completion(request: httpx.Request) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": '{"x": 1}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    return httpx.Response(200, json=body)


async def test_custom_base_url_is_resolved_and_pinned_on_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = [["93.184.216.34"], ["10.0.0.9"]]  # DNS rebinding: public, then internal
    resolved: list[str] = []

    async def resolver(host: str, port: int) -> list[str]:
        resolved.append(host)
        return answers.pop(0)

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _completion(request)

    guarded = partial(ssrf.safe_request, resolver=resolver, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(deepseek, "safe_request", guarded)
    provider = DeepSeekProvider("k", base_url="https://llm.example.com/v1", guard_public=True)
    result = await provider.complete_json(_request())
    assert result.text == '{"x": 1}'
    assert seen[0].url.host == "93.184.216.34" and seen[0].headers["host"] == "llm.example.com"
    with pytest.raises(LLMPermanentError, match="not allowed"):
        await provider.complete_json(_request())  # the second lookup is internal: refused
    assert resolved == ["llm.example.com", "llm.example.com"] and len(seen) == 1


async def test_custom_base_url_to_a_private_literal_is_refused() -> None:
    provider = DeepSeekProvider("k", base_url="https://169.254.169.254/v1", guard_public=True)
    with pytest.raises(LLMPermanentError, match="not allowed"):
        await provider.complete_json(_request())


def test_only_project_supplied_urls_are_guarded() -> None:
    own = row(
        OPENAI_COMPATIBLE,
        key="k",
        base_url="https://llm.example.com/v1",
        judge_model="j",
        caller_model="c",
    )
    env_provider = build_provider(LLMSettings())
    assert isinstance(env_provider, DeepSeekProvider) and env_provider._guard_public is False
    guarded = build_provider(apply_row(LLMSettings(), own))
    assert isinstance(guarded, DeepSeekProvider) and guarded._guard_public is True
    plain = build_provider(apply_row(LLMSettings(), row()))
    assert isinstance(plain, DeepSeekProvider) and plain._guard_public is False
