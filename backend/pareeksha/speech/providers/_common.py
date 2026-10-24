"""Shared plumbing for the HTTP-based adapters."""

from __future__ import annotations

import time
from typing import Any

import httpx

from pareeksha.speech import http
from pareeksha.speech.base import SpeechConfigError, SpeechProviderName
from pareeksha.speech.config import SpeechSettings

DEFAULT_TIMEOUT_S = 60.0


class HTTPAdapter:
    """Owns an ``httpx.AsyncClient`` (or borrows one) and the settings."""

    provider: SpeechProviderName

    def __init__(
        self,
        settings: SpeechSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        retry_delay: float = 1.0,
    ) -> None:
        self.settings = settings or SpeechSettings()
        missing = self.settings.missing_env(self.provider)
        if missing:
            raise SpeechConfigError(f"{self.provider.value}: set {', '.join(missing)} in .env")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)
        self._retry_delay = retry_delay

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return await http.send(self._client, method, url, retry_delay=self._retry_delay, **kwargs)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
