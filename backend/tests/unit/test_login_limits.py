"""Backend login: per-account attempt limit, bounded scrypt concurrency, shape preserved."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Header
from fastapi.security import SecurityScopes

from pareeksha.api import passwords
from pareeksha.api.auth import Principal, authenticate
from pareeksha.api.errors import ApiError, install_error_handlers
from pareeksha.api.passwords import hash_password, verify_password_async
from pareeksha.api.ratelimit import LOGIN_LIMIT, AttemptLimiter
from pareeksha.api.routers import users
from pareeksha.db.session import get_session

PW = "correct horse battery"


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_blocks_after_max_attempts_with_retry_after() -> None:
    clock = Clock()
    limiter = AttemptLimiter(max_attempts=3, window_s=60, clock=clock)
    for _ in range(3):
        limiter.begin("a@x.com")
    clock.now += 10
    with pytest.raises(ApiError) as err:
        limiter.begin("a@x.com")
    assert err.value.status_code == 429
    assert err.value.headers == {"Retry-After": "51"}
    limiter.begin("b@x.com")  # other accounts are unaffected
    clock.now += 51
    limiter.begin("a@x.com")  # the window has passed


def test_success_clears_the_key() -> None:
    limiter = AttemptLimiter(max_attempts=2, window_s=60, clock=Clock())
    limiter.begin("a")
    limiter.begin("a")
    limiter.succeed("a")
    limiter.begin("a")


def test_limiter_memory_is_bounded() -> None:
    limiter = AttemptLimiter(max_keys=100, clock=Clock())
    for i in range(1000):
        limiter.begin(f"user{i}@x.com")
    assert len(limiter._attempts) == 100


class _Session:
    def __init__(self, row: Any) -> None:
        self.row = row

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        return self.row

    async def flush(self) -> None:
        return None


def make_app(row: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(users.router, prefix="/api/v1")
    install_error_handlers(app)

    async def auth(security_scopes: SecurityScopes, x: str = Header(default="")) -> Principal:
        return Principal(key_id=uuid.uuid4(), project_id=uuid.uuid4(), scopes=frozenset({"admin"}))

    app.dependency_overrides[authenticate] = auth
    app.dependency_overrides[get_session] = lambda: _Session(row)
    return app


@pytest.fixture(autouse=True)
def _fresh_limit() -> Iterator[None]:
    LOGIN_LIMIT._attempts.clear()
    yield
    LOGIN_LIMIT._attempts.clear()


def account() -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="a@x.com",
        name="A",
        role="admin",
        disabled_at=None,
        created_at=datetime.now(UTC),
        last_login_at=None,
        password_hash=hash_password(PW),
    )


async def login(app: FastAPI, email: str, password: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_repeated_failures_are_429_even_with_the_right_password_afterwards() -> None:
    app = make_app(account())
    for _ in range(5):
        assert (await login(app, "a@x.com", "wrong password!!")).status_code == 401
    blocked = await login(app, " A@X.com ", PW)  # normalised: same account
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.json()["error"]["code"] == "rate_limited"


async def test_unknown_accounts_are_limited_the_same_way() -> None:
    app = make_app(None)
    codes = [(await login(app, "nobody@x.com", "whatever pass")).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


async def test_successful_login_keeps_its_shape_and_resets_the_count() -> None:
    app = make_app(account())
    for _ in range(4):
        await login(app, "a@x.com", "wrong password!!")
    ok = await login(app, "a@x.com", PW)
    assert ok.status_code == 200
    assert set(ok.json()) == {
        "id",
        "email",
        "name",
        "role",
        "disabled",
        "created_at",
        "last_login_at",
    }
    for _ in range(5):  # the budget is fresh again
        assert (await login(app, "a@x.com", "wrong password!!")).status_code == 401


async def test_password_verification_concurrency_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = peak = 0

    def slow_verify(password: str, stored: str) -> bool:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        import time

        time.sleep(0.05)
        running -= 1
        return True

    monkeypatch.setattr(passwords, "verify_password", slow_verify)
    results = await asyncio.gather(*(verify_password_async("p", "s") for _ in range(20)))
    assert all(results)
    assert 1 <= peak <= passwords.MAX_CONCURRENT_HASHES
