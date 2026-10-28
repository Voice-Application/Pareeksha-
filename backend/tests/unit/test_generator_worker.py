"""The generator worker is registered on the right topic and builds the configured client."""

from __future__ import annotations

import pytest

from pareeksha.events.consumer import REGISTRY
from pareeksha.events.topics import Topics
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMConfigError
from pareeksha.workers import generator


def test_registered_on_the_scenario_topic() -> None:
    assert REGISTRY["generator"].topics == (Topics.SCENARIO_GENERATE_REQUESTED,)


def test_default_llm_uses_the_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    generator._llm_parts.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    try:
        assert isinstance(generator.default_llm(lambda _r: None), LLMClient)
    finally:
        generator._llm_parts.cache_clear()


def test_default_llm_without_a_key_raises_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    generator._llm_parts.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    try:
        with pytest.raises(LLMConfigError):
            generator.default_llm(lambda _r: None)
    finally:
        generator._llm_parts.cache_clear()
