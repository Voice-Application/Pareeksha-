"""The five planted bugs (FR-MK-3). Each toggles independently via ``MOCK_BUGS`` or per call."""

from __future__ import annotations

import os
from collections.abc import Iterable
from enum import StrEnum


class Bug(StrEnum):
    NO_DISCLOSURE = "no_disclosure"  # (1) skips the recording disclosure
    NO_AMOUNT_CONFIRM = "no_amount_confirm"  # (2) never confirms the amount
    ENGLISH_TO_KANNADA = "english_to_kannada"  # (3) replies in English to Kannada callers
    IGNORE_INTERRUPT = "ignore_interrupt"  # (4) barge-in / VAD off while speaking
    FALSE_WAIVER = "false_waiver"  # (5) promises a late-fee waiver it cannot give


def parse_bugs(value: str | Iterable[str] | None) -> frozenset[Bug]:
    """Parse ``"no_disclosure,false_waiver"`` (or an iterable); unknown names raise ValueError."""
    if value is None:
        return frozenset()
    names = value.split(",") if isinstance(value, str) else list(value)
    return frozenset(Bug(n.strip()) for n in names if n.strip())


def bugs_from_env(env: dict[str, str] | None = None) -> frozenset[Bug]:
    source = os.environ if env is None else env
    return parse_bugs(source.get("MOCK_BUGS"))
