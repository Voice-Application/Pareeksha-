"""Download an imported recording through the SSRF guard (FR-IN-5)."""

from __future__ import annotations

import httpx

from pareeksha.audit.ingest import MAX_UPLOAD_BYTES
from pareeksha.audit.pipeline import RecordingFetchError
from pareeksha.integrations.ssrf import Resolver, SSRFError, safe_request, system_resolver

#: Telephony platforms serve recordings as audio/* or as an untyped byte stream.
ALLOWED_CONTENT_TYPES = ("audio/*", "application/octet-stream", "binary/octet-stream")


async def fetch_recording(
    url: str,
    *,
    resolver: Resolver = system_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_s: float = 30.0,
) -> bytes:
    """GET ``url`` (https, public host, no redirects, at most 10 MB, audio content type).

    Raises :class:`RecordingFetchError`: ``retryable`` for network errors, 5xx and 429; permanent
    for a blocked URL, 4xx, wrong content type or an oversized body.
    """
    try:
        response = await safe_request(
            "GET",
            url,
            timeout_s=timeout_s,
            max_bytes=MAX_UPLOAD_BYTES,
            allowed_content_types=ALLOWED_CONTENT_TYPES,
            resolver=resolver,
            transport=transport,
        )
    except SSRFError as exc:
        raise RecordingFetchError(f"blocked: {exc}", retryable=False) from exc
    except (httpx.TransportError, OSError) as exc:
        raise RecordingFetchError(f"network error: {type(exc).__name__}", retryable=True) from exc
    status = response.status_code
    if status >= 500 or status == 429:
        raise RecordingFetchError(f"recording host answered {status}", retryable=True)
    if status != 200:
        raise RecordingFetchError(f"recording host answered {status}", retryable=False)
    return response.content
