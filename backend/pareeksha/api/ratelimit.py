"""A small per-API-key rate limit for the routes that cost LLM money."""

from __future__ import annotations

import time
from collections.abc import Callable
from uuid import UUID

from pareeksha.api.errors import ApiError


class TokenBucket:
    """``rate`` requests per ``per_s`` seconds per key, bursts up to ``rate``.

    ponytail: in-process state, so the limit is per API process (N workers allow N times as many);
    move to Redis or a DB counter if the API is scaled out and the limit must be exact.
    """

    def __init__(
        self, rate: int, per_s: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.rate, self.per_s, self._clock = rate, per_s, clock
        self._state: dict[UUID, tuple[float, float]] = {}  # key -> (tokens, last refill)

    def check(self, key: UUID) -> None:
        now = self._clock()
        tokens, last = self._state.get(key, (float(self.rate), now))
        tokens = min(float(self.rate), tokens + (now - last) * self.rate / self.per_s)
        if tokens < 1:
            wait = max(1, int((1 - tokens) * self.per_s / self.rate) + 1)
            raise ApiError(
                429,
                "rate_limited",
                f"Too many requests: at most {self.rate} per {int(self.per_s)} s per API key",
                {"retry_after_s": wait},
                headers={"Retry-After": str(wait)},
            )
        self._state[key] = (tokens - 1, now)


#: POST /designer/chat: one LLM call (plus a repair retry) per request.
DESIGNER_CHAT_LIMIT = TokenBucket(20)
