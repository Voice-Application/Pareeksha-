"""Error envelope for every non-2xx response: ``{ "error": { "code", "message", "details" } }``.

Status mapping (docs/06-api-spec.md): 400 validation_error, 401 unauthorized, 403 forbidden,
404 not_found, 409 conflict, 402 budget_exceeded, 413 file_too_large, 422 unsupported_audio,
502 upstream_error.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_CODE_BY_STATUS: dict[int, str] = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    402: "budget_exceeded",
    413: "file_too_large",
    422: "unsupported_audio",
    501: "not_implemented",
    502: "upstream_error",
}


class ApiError(Exception):
    """Raise anywhere in a request to produce the standard error response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body), headers=headers)


async def _api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _validation_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(
        400, "validation_error", "Request validation failed", {"errors": exc.errors()}
    )


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _CODE_BY_STATUS.get(
        exc.status_code, HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    )
    headers = dict(exc.headers) if exc.headers else None
    return error_response(exc.status_code, code, str(exc.detail), headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
