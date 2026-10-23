"""Plain data types shared by metrics and checks (no DB or framework imports)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Turn:
    idx: int
    speaker: str  # "caller" | "agent"
    start_ms: int
    end_ms: int
    text: str = ""
    text_masked: str = ""
    ground_truth_text: str | None = None
    agent_heard_text: str | None = None
    language_detected: str | None = None
    is_barge_in: bool = False


@dataclass(frozen=True)
class CheckResult:
    """Mirrors a `deterministic_checks` row. passed=None means not applicable."""

    check_type: str
    check_key: str
    passed: bool | None
    must_pass: bool = True
    evidence_turns: tuple[int, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_type": self.check_type,
            "check_key": self.check_key,
            "must_pass": self.must_pass,
            "passed": self.passed,
            "evidence_turns": list(self.evidence_turns),
            "detail": self.detail,
        }


_FIELDS = (
    "idx",
    "speaker",
    "start_ms",
    "end_ms",
    "text",
    "text_masked",
    "ground_truth_text",
    "agent_heard_text",
    "language_detected",
    "is_barge_in",
)


def as_turn(obj: Any) -> Turn:
    """Coerce a Turn, mapping (dict / DB row mapping) or attribute object into a Turn."""
    if isinstance(obj, Turn):
        return obj
    if isinstance(obj, Mapping):
        data = {k: obj.get(k) for k in _FIELDS}
    else:
        data = {k: getattr(obj, k, None) for k in _FIELDS}
    for k in ("text", "text_masked"):
        data[k] = data[k] or ""
    data["is_barge_in"] = bool(data["is_barge_in"])
    return Turn(**data)


def as_turns(objs: Iterable[Any]) -> list[Turn]:
    return sorted((as_turn(o) for o in objs), key=lambda t: t.idx)


@dataclass
class Disclosure:
    """`agents.mandatory_disclosures` item: {id, text, regex?, within_turns?}."""

    id: str
    text: str
    regex: str | None = None
    within_turns: int | None = (
        None  # only the first N agent turns count; None = whole call
    )
    must_pass: bool = True

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Disclosure:
        return cls(
            id=str(d.get("id") or d.get("text", "")[:40]),
            text=d.get("text", ""),
            regex=d.get("regex"),
            within_turns=d.get("within_turns"),
            must_pass=bool(d.get("must_pass", True)),
        )


@dataclass
class ForbiddenPhrase:
    """`agents.forbidden_phrases` item: {id, text, regex?}."""

    id: str
    text: str
    regex: str | None = None
    must_pass: bool = True

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ForbiddenPhrase:
        return cls(
            id=str(d.get("id") or d.get("text", "")[:40]),
            text=d.get("text", ""),
            regex=d.get("regex"),
            must_pass=bool(d.get("must_pass", True)),
        )


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    turn_idx: int | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ToolCall:
        return cls(
            name=d["name"], args=dict(d.get("args") or {}), turn_idx=d.get("turn_idx")
        )
