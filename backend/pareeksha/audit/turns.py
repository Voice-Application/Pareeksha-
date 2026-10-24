"""Diarized segments -> labelled segments -> caller/agent turns.

Diarization gives anonymous speaker labels. They are normalised to ``spk_0``, ``spk_1``... in order
of first appearance (the keys of ``calls.speaker_map`` and of the override in
``POST /calls/{id}/speaker-map``). A role map ``{label: "caller"|"agent"}`` then turns the labelled
segments into the turns the evaluator reads. The labelled segments are kept as a JSON blob, so a
user override rebuilds the turns without paying for transcription again.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pareeksha.speech.base import TranscriptSegment

Role = Literal["caller", "agent"]
#: Consecutive segments of one role closer than this are one turn (a pause inside a sentence).
MERGE_GAP_MS = 1500


@dataclass(frozen=True)
class LabelledSegment:
    label: str
    start_ms: int
    end_ms: int
    text: str
    #: What the provider called the speaker (``"1"``, ``"2"``, ``None``), kept for the record.
    raw_speaker: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "raw_speaker": self.raw_speaker,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> LabelledSegment:
        return cls(
            label=str(d["label"]),
            start_ms=int(d["start_ms"]),
            end_ms=int(d["end_ms"]),
            text=str(d["text"]),
            raw_speaker=None if d.get("raw_speaker") is None else str(d["raw_speaker"]),
        )


@dataclass(frozen=True)
class BuiltTurn:
    idx: int
    speaker: Role
    start_ms: int
    end_ms: int
    text: str
    is_barge_in: bool = False


def _ms(seconds: float) -> int:
    return max(0, round(seconds * 1000))


def label_segments(segments: Sequence[TranscriptSegment]) -> list[LabelledSegment]:
    """Normalise one diarized transcript: provider labels -> ``spk_N`` by first appearance.

    A segment the provider left unlabelled continues the previous speaker (``spk_0`` at the start).
    """
    names: dict[str, str] = {}
    out: list[LabelledSegment] = []
    previous = "spk_0"
    for seg in sorted(segments, key=lambda s: (s.start_s, s.end_s)):
        text = seg.text.strip()
        if not text:
            continue
        label = (
            previous if seg.speaker is None else names.setdefault(seg.speaker, f"spk_{len(names)}")
        )
        previous = label
        start = _ms(seg.start_s)
        out.append(LabelledSegment(label, start, max(_ms(seg.end_s), start), text, seg.speaker))
    return out


def label_channels(channels: Sequence[Sequence[TranscriptSegment]]) -> list[LabelledSegment]:
    """Channel ``c`` is speaker ``spk_c`` (stereo recordings with one speaker per channel)."""
    out: list[LabelledSegment] = []
    for c, segments in enumerate(channels):
        for seg in segments:
            text = seg.text.strip()
            if text:
                start = _ms(seg.start_s)
                out.append(
                    LabelledSegment(f"spk_{c}", start, max(_ms(seg.end_s), start), text, f"ch{c}")
                )
    return sorted(out, key=lambda s: (s.start_ms, s.end_ms))


def labels_in_order(segments: Sequence[LabelledSegment]) -> list[str]:
    """Speaker labels by first appearance."""
    return list(dict.fromkeys(s.label for s in sorted(segments, key=lambda s: s.start_ms)))


def build_turns(
    segments: Sequence[LabelledSegment],
    roles: Mapping[str, Role],
    *,
    merge_gap_ms: int = MERGE_GAP_MS,
) -> list[BuiltTurn]:
    """Merge consecutive segments of the same role into turns, in time order.

    Raises ``KeyError`` for a label without a role (callers validate first).
    """
    ordered = sorted(segments, key=lambda s: (s.start_ms, s.end_ms))
    merged: list[dict[str, Any]] = []
    for seg in ordered:
        role = roles[seg.label]
        last = merged[-1] if merged else None
        if (
            last is not None
            and last["speaker"] == role
            and seg.start_ms - last["end_ms"] <= merge_gap_ms
        ):
            last["end_ms"] = max(last["end_ms"], seg.end_ms)
            last["text"] = f"{last['text']} {seg.text}"
            continue
        # A caller starting while the agent is still speaking is an interruption.
        barge = bool(
            last is not None
            and role == "caller"
            and last["speaker"] == "agent"
            and seg.start_ms < last["end_ms"]
        )
        merged.append(
            {
                "speaker": role,
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
                "text": seg.text,
                "is_barge_in": barge,
            }
        )
    return [
        BuiltTurn(i, m["speaker"], m["start_ms"], m["end_ms"], m["text"], m["is_barge_in"])
        for i, m in enumerate(merged)
    ]
