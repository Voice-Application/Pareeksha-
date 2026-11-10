"""Retry helper shared by the HTTP providers (3 retries with exponential backoff)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pareeksha.llm.base import LLMRetryableError

T = TypeVar("T")

#: Retries after the first attempt (base.py: "retries these 3 times with backoff").
MAX_RETRIES = 3


async def call_with_retries(
    op: Callable[[], Awaitable[T]],
    *,
    base_delay_s: float = 0.5,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: random.Random | None = None,
) -> T:
    """Run ``op``; on :class:`LLMRetryableError` wait and try again, up to ``MAX_RETRIES`` times.

    A ``retry_after_s`` carried by the error (HTTP ``Retry-After``) wins over the backoff schedule.
    Backoff uses equal jitter (uniform in [ceiling/2, ceiling], as the Gnani client does) so workers
    rate limited together do not retry in lockstep; pass ``rng`` for deterministic tests.
    The last error is re-raised so the consumer framework can route the message to a retry topic.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await op()
        except LLMRetryableError as exc:
            if attempt == MAX_RETRIES:
                raise
            if exc.retry_after_s is not None:
                delay = exc.retry_after_s
            else:
                ceiling = base_delay_s * 2**attempt
                delay = (rng or random).uniform(ceiling / 2, ceiling)
            await sleep(min(delay, 30.0))
    raise AssertionError("unreachable")  # pragma: no cover
