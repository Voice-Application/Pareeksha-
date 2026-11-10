"""A small per-API-key rate limit for the routes that cost LLM money."""

from __future__ import annotations

import time
from collections import OrderedDict
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
        """Init."""
        self.rate, self.per_s, self._clock = rate, per_s, clock
        self._state: dict[UUID, tuple[float, float]] = {}  # key -> (tokens, last refill)

    def check(self, key: UUID) -> None:
        """Check."""
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


class AttemptLimiter:
    """At most ``max_attempts`` sign-in attempts per ``window_s`` seconds per account key.

    An attempt is counted when it starts, so a burst of parallel guesses cannot all slip under the
    limit before the first one fails; a success clears the key. State is bounded: past
    ``max_keys`` the least recently used keys are forgotten (an attacker flooding fresh keys can
    therefore reset an old one, at the price of the memory bound).

    ponytail: in-process, like ``TokenBucket``; move to the database if the API scales out.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_s: float = 300.0,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_attempts, self.window_s, self.max_keys, self._clock = (
            max_attempts,
            window_s,
            max_keys,
            clock,
        )
        self._attempts: OrderedDict[str, list[float]] = OrderedDict()

    def begin(self, key: str) -> None:
        """Count one attempt, or raise 429 with ``Retry-After`` when the key is used up."""
        now = self._clock()
        recent = [t for t in self._attempts.get(key, []) if now - t < self.window_s]
        if len(recent) >= self.max_attempts:
            wait = max(1, int(recent[0] + self.window_s - now) + 1)
            self._attempts[key] = recent
            self._attempts.move_to_end(key)
            raise ApiError(
                429,
                "rate_limited",
                "Too many sign-in attempts for this account; try again later",
                {"retry_after_s": wait},
                headers={"Retry-After": str(wait)},
            )
        recent.append(now)
        self._attempts[key] = recent
        self._attempts.move_to_end(key)
        while len(self._attempts) > self.max_keys:
            self._attempts.popitem(last=False)

    def succeed(self, key: str) -> None:
        """A correct password: forget the key's earlier attempts."""
        self._attempts.pop(key, None)


#: POST /auth/login, keyed by normalised email: a handful of guesses per five minutes.
LOGIN_LIMIT = AttemptLimiter()

#: POST /designer/chat: one LLM call (plus a repair retry) per request.
DESIGNER_CHAT_LIMIT = TokenBucket(20)
#: POST /assistant/chat: one LLM call, sometimes a test plan or a prompt rewrite as well.
ASSISTANT_LIMIT = TokenBucket(30)
#: POST /quick-tests and /improve: a plan or rewrite call, then a run of conversations.
QUICK_TEST_LIMIT = TokenBucket(10)
