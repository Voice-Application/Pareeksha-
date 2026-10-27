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

from dataclasses import dataclass, field

from pareeksha.simulation.models import ToolCallRecord, TurnRecord


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

        taken: set[int] = set()
        for item in sorted(self._said, key=lambda g: g.arrived_ms):
            for i, turn in enumerate(agent):
                if i not in taken and turn.end_ms >= item.arrived_ms:
                    taken.add(i)
                    turn.glass_box_text = item.text
                    break

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
