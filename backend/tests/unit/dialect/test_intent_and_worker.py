"""Intent flag, engine naming and the dialect worker's wiring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pareeksha.dialect.intent import intent_preserved
from pareeksha.dialect.pipeline import engine_provider
from pareeksha.events.consumer import REGISTRY
from pareeksha.events.topics import Topics
from pareeksha.llm.base import (
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMProvider,
    LLMProviderName,
    LLMUsage,
)
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMSettings
from pareeksha.speech.base import SpeechProviderName
from pareeksha.workers import dialect as worker


class Provider(LLMProvider):
    name = LLMProviderName.DEEPSEEK

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.requests: list[JSONCompletionRequest] = []

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        self.requests.append(request)
        return JSONCompletionResult(
            provider=self.name,
            model=request.model,
            text=json.dumps(self.reply),
            usage=LLMUsage(input_tokens=50, output_tokens=5),
            latency_ms=2,
        )

    async def aclose(self) -> None:
        return None


def client(provider: Provider) -> LLMClient:
    settings = LLMSettings(deepseek_api_key="k", deepseek_judge_model="pinned-model")
    return LLMClient(provider, settings)


async def test_identical_texts_need_no_model_call() -> None:
    provider = Provider({"preserved": False})
    out = await intent_preserved(
        client(provider), reference="a", hypothesis="a", language="kn-IN", identical=True
    )
    assert out is True and provider.requests == []


async def test_without_an_llm_the_flag_stays_null() -> None:
    for identical in (True, False):
        out = await intent_preserved(
            None, reference="a", hypothesis="b", language="kn-IN", identical=identical
        )
        assert out is None


async def test_judge_verdict_is_used_with_the_pinned_judge_model_at_temperature_zero() -> None:
    provider = Provider({"preserved": False, "reason": "amount changed"})
    out = await intent_preserved(
        client(provider),
        reference="ಐದು ಸಾವಿರ",
        hypothesis="ಐವತ್ತು ಸಾವಿರ",
        language="kn-IN",
        identical=False,
    )
    assert out is False
    req = provider.requests[0]
    assert req.model == "pinned-model" and req.temperature == 0.0 and not req.thinking
    prompt = req.messages[0].content
    assert "ಐದು ಸಾವಿರ" in prompt and "ಐವತ್ತು ಸಾವಿರ" in prompt and "json" in prompt.lower()


async def test_empty_hypothesis_is_described_not_blank() -> None:
    provider = Provider({"preserved": False})
    await intent_preserved(
        client(provider), reference="x", hypothesis="", language="hi-IN", identical=False
    )
    assert "(nothing)" in provider.requests[0].messages[0].content


def test_engine_names_map_to_providers() -> None:
    assert engine_provider("gnani-prisma") is SpeechProviderName.GNANI
    assert engine_provider("deepgram-nova-3") is SpeechProviderName.DEEPGRAM
    assert engine_provider("azure") is SpeechProviderName.AZURE
    with pytest.raises(ValueError, match="unknown engine 'whisper-large-v3'"):
        engine_provider("whisper-large-v3")


def test_worker_registers_the_dialect_group_on_the_clip_topic() -> None:
    assert REGISTRY["dialect"].topics == (Topics.DIALECT_CLIP_REQUESTED,)


def test_worker_deps_use_data_dir_and_skip_llm_without_a_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    worker._llm_parts.cache_clear()
    deps = worker.make_deps()
    assert deps.data_dir == tmp_path
    assert deps.llm_for(lambda _r: None) is None
    worker._llm_parts.cache_clear()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    assert isinstance(deps.llm_for(lambda _r: None), LLMClient)
    worker._llm_parts.cache_clear()
