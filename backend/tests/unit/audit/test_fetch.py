"""Imported recordings are downloaded through the SSRF guard."""

from __future__ import annotations

import httpx
import pytest

from pareeksha.audit.fetch import fetch_recording
from pareeksha.audit.pipeline import RecordingFetchError


async def public(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


async def private(host: str, port: int) -> list[str]:
    return ["10.0.0.5"]


def serving(
    status: int, body: bytes = b"RIFFdata", ctype: str = "audio/wav"
) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(status, content=body, headers={"content-type": ctype})
    )


URL = "https://calls.example.com/rec/1.wav"


async def test_downloads_audio() -> None:
    data = await fetch_recording(URL, resolver=public, transport=serving(200))
    assert data == b"RIFFdata"


async def test_octet_stream_is_accepted() -> None:
    transport = serving(200, ctype="application/octet-stream")
    assert await fetch_recording(URL, resolver=public, transport=transport) == b"RIFFdata"


@pytest.mark.parametrize(
    ("url", "resolver", "transport"),
    [
        ("http://calls.example.com/a.wav", public, serving(200)),  # not https
        (URL, private, serving(200)),  # resolves to a private address
        (URL, public, serving(200, ctype="text/html")),  # not audio
        (URL, public, serving(404)),
        (URL, public, serving(403)),
    ],
)
async def test_permanent_failures(
    url: str, resolver: object, transport: httpx.MockTransport
) -> None:
    with pytest.raises(RecordingFetchError) as err:
        await fetch_recording(url, resolver=resolver, transport=transport)  # type: ignore[arg-type]
    assert err.value.retryable is False


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_server_errors_are_retryable(status: int) -> None:
    with pytest.raises(RecordingFetchError) as err:
        await fetch_recording(URL, resolver=public, transport=serving(status))
    assert err.value.retryable is True


async def test_network_errors_are_retryable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(RecordingFetchError) as err:
        await fetch_recording(URL, resolver=public, transport=httpx.MockTransport(boom))
    assert err.value.retryable is True
