"""Request-body cap, and the inbound webhook's order: size, then signature, then JSON."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Annotated, Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI, File, Request, UploadFile

from pareeksha.api.body_limit import body_capped_route
from pareeksha.api.errors import install_error_handlers
from pareeksha.api.routers import webhooks
from pareeksha.db.session import get_session
from pareeksha.integrations.signing import sign_headers

CAP = 1000


def capped_app() -> FastAPI:
    router = APIRouter(route_class=body_capped_route(CAP, "too big", slack=0))

    @router.post("/raw")
    async def raw(request: Request) -> dict[str, int]:
        return {"n": len(await request.body())}

    @router.post("/upload")
    async def upload(file: Annotated[UploadFile, File()]) -> dict[str, int]:
        return {"n": len(await file.read())}

    app = FastAPI()
    app.include_router(router)
    install_error_handlers(app)
    return app


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def chunks(total: int, size: int = 100) -> AsyncIterator[bytes]:
    for _ in range(total // size):
        yield b"x" * size


async def test_declared_length_over_cap_is_413() -> None:
    async with client(capped_app()) as c:
        response = await c.post("/raw", content=b"x" * (CAP + 1))
    assert response.status_code == 413
    assert response.json()["error"] == {
        "code": "file_too_large",
        "message": "too big",
        "details": {"max_bytes": CAP},
    }


async def test_body_at_the_cap_is_accepted() -> None:
    async with client(capped_app()) as c:
        response = await c.post("/raw", content=b"x" * CAP)
    assert response.status_code == 200 and response.json() == {"n": CAP}


async def test_streamed_body_without_length_is_stopped_at_the_cap() -> None:
    seen = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal seen
        async for part in chunks(100_000):
            seen += len(part)
            yield part

    async with client(capped_app()) as c:
        response = await c.post("/raw", content=body())
    assert response.status_code == 413
    assert seen <= CAP + 200  # the rest of the body was never pulled


async def test_streamed_multipart_over_cap_is_413_not_parse_error() -> None:
    async with client(capped_app()) as c:
        response = await c.post(
            "/upload", files={"file": ("a.bin", b"x" * (CAP * 5), "application/octet-stream")}
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


async def test_limit_can_be_a_callable_read_per_request() -> None:
    limit = [10]
    router = APIRouter(route_class=body_capped_route(lambda: limit[0], "too big", slack=0))

    @router.post("/raw")
    async def raw(request: Request) -> dict[str, int]:
        return {"n": len(await request.body())}

    app = FastAPI()
    app.include_router(router)
    install_error_handlers(app)
    async with client(app) as c:
        assert (await c.post("/raw", content=b"x" * 20)).status_code == 413
        limit[0] = 100
        assert (await c.post("/raw", content=b"x" * 20)).status_code == 200


SECRET = "s3cret-s3cret-s3cret-0001"
ID = uuid.uuid4()


class _Session:
    """Reports the external id as already ingested, so a request that gets past parsing ends
    with a duplicate answer and touches nothing else."""

    async def scalar(self, *args: Any, **kwargs: Any) -> uuid.UUID:
        return uuid.UUID(int=7)


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    async def source(session: Any, integration_id: uuid.UUID) -> Any:
        return SimpleNamespace(id=integration_id)

    monkeypatch.setattr(webhooks, "_source_integration", source)
    monkeypatch.setattr(webhooks, "_stored_secrets", lambda row: {"signing_secret": SECRET})
    app = FastAPI()
    app.include_router(webhooks.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = lambda: _Session()
    install_error_handlers(app)
    return client(app)


def payload() -> bytes:
    return json.dumps(
        {"external_id": "e-1", "recording_url": "https://8.8.8.8/a.mp3", "language": "kn-IN"}
    ).encode()


async def post(c: httpx.AsyncClient, raw: bytes, secret: str = SECRET) -> httpx.Response:
    return await c.post(
        f"/api/v1/webhooks/inbound/{ID}", content=raw, headers=sign_headers(secret, raw)
    )


async def test_valid_signed_body_is_accepted(hook: httpx.AsyncClient) -> None:
    async with hook as c:
        response = await post(c, payload())
    assert response.status_code == 202 and response.json()["duplicate"] is True


async def test_unsigned_malformed_json_is_401_not_a_validation_error(
    hook: httpx.AsyncClient,
) -> None:
    async with hook as c:
        response = await post(c, b"{not json", secret="wrong-secret-wrong-secret")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_signature"


async def test_signed_malformed_json_is_400_without_echoing_input(hook: httpx.AsyncClient) -> None:
    raw = json.dumps({"external_id": "e", "language": "kn-IN", "recording_url": ["TOPSECRET"]})
    async with hook as c:
        response = await post(c, raw.encode())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert "TOPSECRET" not in response.text


async def test_oversized_body_is_413_before_any_signature_work(hook: httpx.AsyncClient) -> None:
    raw = b" " * (webhooks.MAX_WEBHOOK_BODY_BYTES + 1)
    async with hook as c:
        response = await post(c, raw)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_oversized_chunked_body_is_413(hook: httpx.AsyncClient) -> None:
    size = webhooks.MAX_WEBHOOK_BODY_BYTES + 65536

    async with hook as c:
        response = await c.post(
            f"/api/v1/webhooks/inbound/{ID}",
            content=chunks(size, 65536),
            headers={"X-Pareeksha-Timestamp": "1", "X-Pareeksha-Signature": "v1=00"},
        )
    assert response.status_code == 413
