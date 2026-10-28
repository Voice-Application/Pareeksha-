"""Turn assembly (FR-RN-8): caller turns, agent turns, glass-box text and tool calls.

Pure bookkeeping, no I/O. Everything is stamped on the call clock when it happens; ``build`` then
orders the turns by start time and attaches the glass-box items by time:

- ``user`` transcripts (what the agent's STT heard) belong to the latest caller turn that started
  before they arrived;
- ``agent`` transcripts (what the agent is about to say) belong to the first agent turn that is
  not over when they arrive;
- tool calls belong to the latest agent turn that started before them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pareeksha.simulation.models import ToolCallRecord, TurnRecord

_SCRIPT_LANGUAGES = (
    ("kn-IN", re.compile(r"[\u0c80-\u0cff]")),
    ("hi-IN", re.compile(r"[\u0900-\u097f]")),
    ("en-IN", re.compile(r"[A-Za-z]")),
)


def script_language(text: str) -> str | None:
    """Language of the glass-box text by dominant script (None when under 3 letters)."""
    counts = [(lang, len(rx.findall(text))) for lang, rx in _SCRIPT_LANGUAGES]
    if sum(n for _, n in counts) < 3:
        return None
    return max(counts, key=lambda c: c[1])[0]


@dataclass
class _GlassText:
    arrived_ms: int
    text: str


@dataclass
class _Tool:
    arrived_ms: int
    name: str
    arguments: dict[str, object]
    result: dict[str, object] | None


@dataclass
class TurnTracker:
    _caller: list[TurnRecord] = field(default_factory=list)
    _agent: list[TurnRecord] = field(default_factory=list)
    _heard: list[_GlassText] = field(default_factory=list)
    _said: list[_GlassText] = field(default_factory=list)
    _tools: list[_Tool] = field(default_factory=list)

    @property
    def agent_turns(self) -> int:
        return len(self._agent)

    @property
    def caller_turns(self) -> int:
        return len(self._caller)

    @property
    def glass_box_seen(self) -> bool:
        return bool(self._heard or self._said or self._tools)

    def add_caller_turn(
        self,
        *,
        start_ms: int,
        end_ms: int,
        ground_truth: str,
        is_barge_in: bool = False,
        kind: str = "reply",
    ) -> None:
        self._caller.append(
            TurnRecord(
                idx=-1,
                speaker="caller",
                text=ground_truth,
                ground_truth_text=ground_truth,
                start_ms=start_ms,
                end_ms=max(end_ms, start_ms),
                is_barge_in=is_barge_in,
                kind=kind,
            )
        )

    def add_agent_turn(
        self,
        *,
        start_ms: int,
        end_ms: int,
        text: str,
        confidence: float | None = None,
        language: str | None = None,
    ) -> None:
        self._agent.append(
            TurnRecord(
                idx=-1,
                speaker="agent",
                text=text,
                start_ms=start_ms,
                end_ms=max(end_ms, start_ms),
                language_detected=language,
                stt_confidence=confidence,
            )
        )

    def add_agent_heard(self, arrived_ms: int, text: str) -> None:
        self._heard.append(_GlassText(arrived_ms, text))

    def add_agent_said(self, arrived_ms: int, text: str) -> None:
        self._said.append(_GlassText(arrived_ms, text))

    def add_tool_call(
        self,
        arrived_ms: int,
        name: str,
        arguments: dict[str, object],
        result: dict[str, object] | None,
    ) -> None:
        self._tools.append(_Tool(arrived_ms, name, arguments, result))

    def build(self) -> tuple[list[TurnRecord], list[ToolCallRecord]]:
        caller = sorted((t.model_copy() for t in self._caller), key=lambda t: t.start_ms)
        agent = sorted((t.model_copy() for t in self._agent), key=lambda t: t.start_ms)

        for item in sorted(self._heard, key=lambda g: g.arrived_ms):
            owner = None
            for turn in caller:
                if turn.start_ms <= item.arrived_ms:
                    owner = turn
            if owner is not None:
                owner.agent_heard_text = (
                    f"{owner.agent_heard_text} {item.text}".strip()
                    if owner.agent_heard_text
                    else item.text
                )

        # A text belongs to the first agent turn that has not ended before it arrived. A reply cut
        # off by the caller before any of its audio is heard leaves a text that arrived ahead of
        # the next reply's own: texts that both precede a turn's audio, the latest one was spoken.
        # A text that arrives while a turn is already labelled belongs to the following turn.
        owned_early: set[int] = set()
        for item in sorted(self._said, key=lambda g: g.arrived_ms):
            for i, turn in enumerate(agent):
                if turn.end_ms < item.arrived_ms:
                    continue
                early = item.arrived_ms < turn.start_ms
                if turn.glass_box_text is not None and not (early and i in owned_early):
                    continue
                turn.glass_box_text = item.text
                if early:
                    owned_early.add(i)
                break

        # The STT of an agent turn runs in the call's language, so it transliterates a reply in
        # another language into that script (English spoken to a Kannada caller reads as Kannada).
        # What the bot actually said, when it reports it, is the evidence for the language.
        for turn in agent:
            if turn.glass_box_text and (spoken := script_language(turn.glass_box_text)):
                turn.language_detected = spoken

        turns = sorted([*caller, *agent], key=lambda t: (t.start_ms, t.speaker != "agent"))
        for idx, turn in enumerate(turns):
            turn.idx = idx

        calls: list[ToolCallRecord] = []
        for seq, tool in enumerate(sorted(self._tools, key=lambda x: x.arrived_ms)):
            owner_idx: int | None = None
            for turn in turns:
                if turn.speaker == "agent" and turn.start_ms <= tool.arrived_ms:
                    owner_idx = turn.idx
            calls.append(
                ToolCallRecord(
                    seq=seq,
                    name=tool.name,
                    arguments=tool.arguments,
                    result=tool.result,
                    at_ms=tool.arrived_ms,
                    turn_idx=owner_idx,
                )
            )
        return turns, calls
