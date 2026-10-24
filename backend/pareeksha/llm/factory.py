"""Build the configured provider/client from settings (``LLM_PROVIDER``)."""

from __future__ import annotations

import httpx

from pareeksha.llm.base import LLMProvider, LLMProviderName
from pareeksha.llm.client import JSONCache, LLMClient, UsageSink
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.deepseek import DeepSeekProvider
from pareeksha.llm.gemini import GeminiProvider


def build_provider(
    settings: LLMSettings, *, http_client: httpx.AsyncClient | None = None
) -> LLMProvider:
    """Provider for ``settings.llm_provider``; raises ``LLMConfigError`` if its key is missing."""
    key = settings.api_key
    if settings.llm_provider is LLMProviderName.DEEPSEEK:
        return DeepSeekProvider(key, base_url=settings.deepseek_base_url, http_client=http_client)
    return GeminiProvider(key, http_client=http_client)


def build_client(
    settings: LLMSettings | None = None,
    *,
    usage_sink: UsageSink | None = None,
    cache: JSONCache | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> LLMClient:
    settings = settings or LLMSettings()
    return LLMClient(
        build_provider(settings, http_client=http_client),
        settings,
        usage_sink=usage_sink,
        cache=cache,
    )
