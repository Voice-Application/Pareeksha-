"""Jittered backoff in the shared LLM retry helper."""

from __future__ import annotations

import random

import pytest

from pareeksha.llm._retry import MAX_RETRIES, call_with_retries
from pareeksha.llm.base import LLMRetryableError


async def _run(err: LLMRetryableError, seed: int | None = 7) -> list[float]:
    delays: list[float] = []

    async def sleep(s: float) -> None:
        delays.append(s)

    async def op() -> None:
        raise err

    with pytest.raises(LLMRetryableError):
        await call_with_retries(
            op, base_delay_s=1.0, sleep=sleep, rng=random.Random(seed) if seed is not None else None
        )
    return delays


async def test_backoff_delays_are_jittered_within_bounds() -> None:
    delays = await _run(LLMRetryableError("429"))
    assert len(delays) == MAX_RETRIES
    for attempt, delay in enumerate(delays):
        ceiling = 1.0 * 2**attempt
        assert ceiling / 2 <= delay <= ceiling
    assert delays != [0.5 * 2 ** (a + 1) for a in range(MAX_RETRIES)]
    assert delays != [1.0 * 2**a for a in range(MAX_RETRIES)]


async def test_same_seed_gives_same_delays_and_seeds_differ() -> None:
    err = LLMRetryableError("429")
    assert await _run(err, 1) == await _run(err, 1)
    assert await _run(err, 1) != await _run(err, 2)


async def test_retry_after_is_used_unshortened_and_capped_at_30s() -> None:
    assert await _run(LLMRetryableError("429", retry_after_s=4.0)) == [4.0] * MAX_RETRIES
    assert await _run(LLMRetryableError("429", retry_after_s=99.0)) == [30.0] * MAX_RETRIES
