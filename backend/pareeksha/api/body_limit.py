"""Request-body size cap for routes that take uploads or signed raw bodies."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import HTTPException
from fastapi.routing import APIRoute
from starlette.types import Message

from pareeksha.api.errors import ApiError

#: Room for the multipart envelope around a file of the route's maximum size.
MULTIPART_SLACK = 1024 * 1024


class _BodyTooLarge(HTTPException):
    """Raised from the receive channel. It must be an ``HTTPException`` because FastAPI turns any
    other error raised while it parses the body into a 400."""

    def __init__(self) -> None:
        super().__init__(413, "request body too large")


def body_capped_route(
    max_bytes: int | Callable[[], int],
    message: str,
    *,
    slack: int = MULTIPART_SLACK,
    code: str = "file_too_large",
) -> type[APIRoute]:
    """A route class answering 413 once the body exceeds ``max_bytes`` + ``slack``.

    ``Content-Length`` is checked first, then bytes are counted as the body streams in, so a
    chunked body (no length) or a lying length is stopped without being buffered. ``max_bytes``
    may be a callable, read per request. ``details.max_bytes`` reports ``max_bytes`` itself."""

    def limit() -> int:
        return max_bytes() if callable(max_bytes) else max_bytes

    def too_large() -> ApiError:
        return ApiError(413, code, message, {"max_bytes": limit()})

    class BodyCappedRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def capped(request: Request) -> Response:
                cap = limit() + slack
                try:
                    declared = int(request.headers.get("content-length") or 0)
                except ValueError:
                    declared = 0
                if declared > cap:
                    raise too_large()
                seen = 0

                async def receive() -> Message:
                    nonlocal seen
                    msg = await request.receive()
                    if msg["type"] == "http.request":
                        seen += len(msg.get("body", b""))
                        if seen > cap:
                            raise _BodyTooLarge
                    return msg

                try:
                    return await handler(Request(request.scope, receive))
                except _BodyTooLarge as exc:
                    raise too_large() from exc

            return capped

    return BodyCappedRoute
