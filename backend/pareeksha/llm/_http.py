"""HTTP error classification shared by the providers."""

from __future__ import annotations

import httpx

from pareeksha.llm.base import LLMError, LLMPermanentError, LLMRetryableError


def retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def classify_status(response: httpx.Response, provider: str) -> LLMError | None:
    """Map a non-2xx response to the contract's error types; ``None`` when it is a success."""
    if response.is_success:
        return None
    detail = response.text[:300].replace("\n", " ")
    message = f"{provider} HTTP {response.status_code}: {detail}"
    if response.status_code in (408, 409, 425, 429) or response.status_code >= 500:
        return LLMRetryableError(message, retry_after_s=retry_after_seconds(response))
    return LLMPermanentError(message)


def classify_transport(exc: httpx.HTTPError, provider: str) -> LLMRetryableError:
    return LLMRetryableError(f"{provider} transport error: {type(exc).__name__}: {exc}")
