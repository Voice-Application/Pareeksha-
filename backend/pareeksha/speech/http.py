"""Shared async HTTP call with the retry policy of TRD section 3: 5xx, 429 and timeouts retry."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from pareeksha.speech.base import SpeechPermanentError, SpeechRetryableError

ATTEMPTS = 3


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


async def send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retry_delay: float = 1.0,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request; retry 5xx / 429 / transport errors 3 times, raise typed errors otherwise."""
    last = "no attempt made"
    retry_after: float | None = None
    for attempt in range(ATTEMPTS):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:  # timeouts, connection errors
            last, retry_after = f"{type(exc).__name__}: {exc}", None
        else:
            if response.status_code < 400:
                return response
            detail = f"HTTP {response.status_code}: {response.text[:300]}"
            if response.status_code < 500 and response.status_code != 429:
                raise SpeechPermanentError(detail)
            last, retry_after = detail, _retry_after(response)
        if attempt < ATTEMPTS - 1:
            await asyncio.sleep(retry_delay * 2**attempt)
    raise SpeechRetryableError(last, retry_after_s=retry_after)
