"""Build a ``ChatProvider`` for a ``ProviderName``."""

from __future__ import annotations

import httpx

from pareeksha.agent_llm.anthropic import AnthropicProvider
from pareeksha.agent_llm.base import ChatProvider
from pareeksha.agent_llm.gemini import GeminiProvider
from pareeksha.agent_llm.openai_compat import OpenAICompatProvider
from pareeksha.schemas.prompts import ProviderName

DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "ollama": "http://localhost:11434/v1",
}


def build_chat_provider(
    provider: ProviderName,
    *,
    api_key: str | None,
    base_url: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> ChatProvider:
    if provider == "anthropic":
        return AnthropicProvider(base_url, api_key, http)
    if provider == "gemini":
        return GeminiProvider(base_url, api_key, http)
    if provider == "openai_compatible":
        if not base_url:
            raise ValueError("openai_compatible requires base_url")
        return OpenAICompatProvider(base_url, api_key, http)
    return OpenAICompatProvider(base_url or DEFAULT_BASE_URLS[provider], api_key, http)
