"""SDK exceptions. ``ApiError`` mirrors the platform error envelope."""

from __future__ import annotations

from typing import Any


class PareekshaError(Exception):
    """Base class for every SDK error."""


class ApiError(PareekshaError):
    """Non-2xx response: ``{"error": {"code", "message", "details"}}``."""

    def __init__(
        self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class NotFoundError(PareekshaError):
    """A named resource (agent, scenario, persona, noise profile) does not exist."""


class WaitTimeoutError(PareekshaError):
    """``runs.wait`` gave up before the run reached a final status."""


class ConfigError(PareekshaError):
    """Invalid ``pareeksha.yaml`` or CLI profile."""
