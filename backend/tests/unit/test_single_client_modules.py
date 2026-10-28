"""NFR-12: Gnani and LLM provider HTTP/SDK calls live only in their client modules."""

from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "pareeksha"

# Hosts / SDKs only the owning module may reference. Allowed: where each lives.
RULES = {
    r"api\.deepseek\.com": {"llm"},
    r"generativelanguage\.googleapis\.com|google\.genai|google\.generativeai": {"llm"},
    r"inya\.ai|gnani\.ai": {"gnani", "speech"},
    r"^\s*(from|import)\s+gnani\b": {"gnani", "speech"},
}


def _top(path: Path) -> str:
    return path.relative_to(PKG).parts[0]


def test_provider_calls_only_in_their_modules() -> None:
    offenders = []
    for path in PKG.rglob("*.py"):
        text = path.read_text()
        for pattern, allowed in RULES.items():
            if re.search(pattern, text, re.M) and _top(path) not in allowed:
                offenders.append(f"{path.relative_to(PKG)} matches {pattern!r}")
    assert not offenders, offenders
