"""Put the system prompt under test in front of the scenario generator and the judge."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def prompt_context(description: str, version: Mapping[str, Any] | None) -> str:
    """``description`` unchanged without a version, else with its system prompt appended."""
    if version is None:
        return description
    return f"{description}\n\nSystem prompt under test:\n{version['system_prompt']}"
