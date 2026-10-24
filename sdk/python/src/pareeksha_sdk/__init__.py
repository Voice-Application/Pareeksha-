"""Pareeksha Python SDK and CLI.

The import name is ``pareeksha_sdk`` (not ``pareeksha``) so it can be installed next to the
backend package, which owns the ``pareeksha`` name.
"""

from pareeksha_sdk.client import AsyncPareeksha, Pareeksha
from pareeksha_sdk.errors import (
    ApiError,
    ConfigError,
    NotFoundError,
    PareekshaError,
    WaitTimeoutError,
)

__all__ = [
    "ApiError",
    "AsyncPareeksha",
    "ConfigError",
    "NotFoundError",
    "Pareeksha",
    "PareekshaError",
    "WaitTimeoutError",
]
