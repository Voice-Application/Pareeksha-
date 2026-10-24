"""Interface and configuration tests for llm/base.py and llm/config.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pareeksha.llm.base import (
    ChatMessage,
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMPermanentError,
    LLMProvider,
    LLMProviderName,
    LLMPurpose,
    LLMRetryableError,
    LLMUsage,
)
from pareeksha.llm.config import (
    DEEPSEEK_DEFAULT_BASE_URL,
    LLMConfigError,
    LLMSettings,
)

ENV_VARS = [
    "LLM_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_JUDGE_MODEL",
    "DEEPSEEK_CALLER_MODEL",
    "COST_DEEPSEEK_PER_1K_INPUT_TOKENS",
    "COST_DEEPSEEK_PER_1K_OUTPUT_TOKENS",
    "GEMINI_API_KEY",
    "GEMINI_JUDGE_MODEL",
    "GEMINI_CALLER_MODEL",
    "COST_GEMINI_PER_1K_INPUT_TOKENS",
    "COST_GEMINI_PER_1K_OUTPUT_TOKENS",
    "JUDGE_TEMPERATURE",
    "CALLER_TEMPERATURE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(str(tmp_path))  # no stray .env


class FakeProvider(LLMProvider):
    name = LLMProviderName.DEEPSEEK

    def __init__(self) -> None:
        self.closed = False

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        return JSONCompletionResult(
            provider=self.name,
            model=request.model,
            text='{"ok": true}',
            usage=LLMUsage(input_tokens=120, output_tokens=8),
            finish_reason="stop",
            latency_ms=12,
        )

    async def aclose(self) -> None:
        self.closed = True


def _request(**overrides: object) -> JSONCompletionRequest:
    base: dict[str, object] = {
        "purpose": LLMPurpose.JUDGE,
        "model": "deepseek-v4-pro",
        "messages": [ChatMessage(role="user", content="Reply in json: {}")],
    }
    return JSONCompletionRequest.model_validate({**base, **overrides})


def test_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]

    class Half(LLMProvider):
        name = LLMProviderName.GEMINI

        async def aclose(self) -> None: ...

    with pytest.raises(TypeError, match="complete_json"):
        Half()  # type: ignore[abstract]


async def test_provider_round_trip() -> None:
    provider = FakeProvider()
    result = await provider.complete_json(_request())
    assert result.text == '{"ok": true}'
    assert result.usage.total_tokens == 128
    assert result.provider is LLMProviderName.DEEPSEEK
    await provider.aclose()
    assert provider.closed


def test_request_defaults_and_validation() -> None:
    request = _request()
    assert request.temperature == 0.0
    assert (
        request.thinking is False
    )  # deterministic by default (DeepSeek thinking ignores temperature)
    assert request.json_schema is None
    bad_values: list[dict[str, object]] = [
        {"messages": []},
        {"model": ""},
        {"temperature": 2.5},
        {"max_output_tokens": 0},
    ]
    for bad in bad_values:
        with pytest.raises(ValidationError):
            _request(**bad)
    with pytest.raises(ValidationError):
        _request(surprise=1)
    with pytest.raises(ValidationError):
        ChatMessage(role="tool", content="x")  # type: ignore[arg-type]


def test_usage_validation() -> None:
    with pytest.raises(ValidationError):
        LLMUsage(input_tokens=-1, output_tokens=0)


def test_error_classes() -> None:
    err = LLMRetryableError("429", retry_after_s=3)
    assert err.retry_after_s == 3
    assert not issubclass(LLMRetryableError, LLMPermanentError)


def test_default_provider_is_deepseek_with_documented_models() -> None:
    settings = LLMSettings()
    assert settings.llm_provider is LLMProviderName.DEEPSEEK
    assert settings.deepseek_base_url == DEEPSEEK_DEFAULT_BASE_URL == "https://api.deepseek.com"
    assert settings.judge_model == "deepseek-v4-pro"
    assert settings.caller_model == "deepseek-flash"
    assert settings.judge_temperature == 0 and settings.caller_temperature == 0.7


def test_env_selects_provider_and_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("GEMINI_JUDGE_MODEL", "gemini-judge-pinned")
    monkeypatch.setenv("GEMINI_CALLER_MODEL", "gemini-caller-pinned")
    settings = LLMSettings()
    assert settings.llm_provider is LLMProviderName.GEMINI
    assert settings.api_key == "g-key"
    assert settings.model_for(LLMPurpose.JUDGE) == "gemini-judge-pinned"
    assert settings.model_for(LLMPurpose.CALLER) == "gemini-caller-pinned"


def test_invalid_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ValidationError):
        LLMSettings()


def test_missing_key_and_unpinned_gemini_model_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(LLMConfigError, match="API key"):
        _ = LLMSettings().api_key
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")  # empty means unset (.env.example has blanks)
    with pytest.raises(LLMConfigError):
        _ = LLMSettings().api_key
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(LLMConfigError, match="GEMINI_JUDGE_MODEL"):
        _ = LLMSettings().judge_model


def test_model_and_temperature_per_purpose() -> None:
    settings = LLMSettings()
    judge_like = (LLMPurpose.JUDGE, LLMPurpose.ROLE_DETECT, LLMPurpose.ASR_INTENT)
    for purpose in judge_like:
        assert settings.model_for(purpose) == "deepseek-v4-pro"
        assert settings.temperature_for(purpose) == 0
    assert settings.model_for(LLMPurpose.CALLER) == "deepseek-flash"
    assert settings.model_for(LLMPurpose.SCENARIO_GEN) == "deepseek-flash"
    assert settings.temperature_for(LLMPurpose.CALLER) == 0.7
    assert settings.temperature_for(LLMPurpose.SCENARIO_GEN) == 0.8


def test_estimate_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = LLMUsage(input_tokens=2000, output_tokens=500)
    assert LLMSettings().estimate_cost(usage) is None  # rates not configured
    monkeypatch.setenv("COST_DEEPSEEK_PER_1K_INPUT_TOKENS", "0.001")
    monkeypatch.setenv("COST_DEEPSEEK_PER_1K_OUTPUT_TOKENS", "0.004")
    cost = LLMSettings().estimate_cost(usage)
    assert cost == pytest.approx(2 * 0.001 + 0.5 * 0.004)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert LLMSettings().estimate_cost(usage) is None  # gemini rates are separate
    monkeypatch.setenv("COST_GEMINI_PER_1K_INPUT_TOKENS", "0.01")
    monkeypatch.setenv("COST_GEMINI_PER_1K_OUTPUT_TOKENS", "0.02")
    assert LLMSettings().estimate_cost(usage) == pytest.approx(0.03)


def test_env_example_declares_every_llm_variable() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / ".env.example").read_text(encoding="utf-8")
    for name in ENV_VARS:
        assert f"{name}=" in text, f"{name} missing from .env.example"
    assert "LLM_PROVIDER=deepseek" in text
