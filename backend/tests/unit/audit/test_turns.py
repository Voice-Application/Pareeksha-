"""Diarized segments -> labels -> turns."""

from __future__ import annotations

from pareeksha.audit.turns import (
    LabelledSegment,
    build_turns,
    label_channels,
    label_segments,
    labels_in_order,
)
from pareeksha.speech.base import TranscriptSegment


def seg(text: str, start: float, end: float, speaker: str | None) -> TranscriptSegment:
    return TranscriptSegment(text=text, start_s=start, end_s=end, speaker=speaker)


def test_labels_follow_first_appearance_not_the_provider_numbering() -> None:
    out = label_segments(
        [seg("b", 5.0, 6.0, "1"), seg("a", 0.0, 1.0, "2"), seg("c", 2.0, 3.0, "1")],
    )
    assert [(s.label, s.text) for s in out] == [("spk_0", "a"), ("spk_1", "c"), ("spk_1", "b")]
    assert out[0].raw_speaker == "2" and out[0].start_ms == 0 and out[2].end_ms == 6000


def test_unlabelled_segment_continues_the_previous_speaker_and_blanks_are_dropped() -> None:
    out = label_segments(
        [seg("x", 0.0, 1.0, None), seg("  ", 1.0, 2.0, "1"), seg("y", 2.0, 3.0, "1")],
    )
    assert [s.label for s in out] == ["spk_0", "spk_0"]
    assert labels_in_order(out) == ["spk_0"]


def test_channels_are_speakers_by_index() -> None:
    out = label_channels(
        [[seg("agent hello", 0.0, 2.0, "1")], [seg("caller yes", 1.0, 2.5, None)]],
    )
    assert [(s.label, s.start_ms) for s in out] == [("spk_0", 0), ("spk_1", 1000)]
    assert out[1].raw_speaker == "ch1"


def segments() -> list[LabelledSegment]:
    return [
        LabelledSegment("spk_0", 0, 2000, "namaste"),
        LabelledSegment("spk_0", 2400, 4000, "this call is recorded"),
        LabelledSegment("spk_1", 4500, 6000, "haan boliye"),
        LabelledSegment("spk_0", 9000, 11000, "your emi is due"),
    ]


def test_same_role_segments_merge_when_the_gap_is_short() -> None:
    turns = build_turns(segments(), {"spk_0": "agent", "spk_1": "caller"})
    assert [(t.idx, t.speaker, t.start_ms, t.end_ms) for t in turns] == [
        (0, "agent", 0, 4000),
        (1, "caller", 4500, 6000),
        (2, "agent", 9000, 11000),
    ]
    assert turns[0].text == "namaste this call is recorded"
    assert not any(t.is_barge_in for t in turns)


def test_swapping_roles_swaps_every_turn() -> None:
    a = build_turns(segments(), {"spk_0": "agent", "spk_1": "caller"})
    b = build_turns(segments(), {"spk_0": "caller", "spk_1": "agent"})
    assert [t.speaker for t in b] == ["caller" if t.speaker == "agent" else "agent" for t in a]
    assert [t.text for t in a] == [t.text for t in b]


def test_two_labels_with_the_same_role_collapse_into_one_turn() -> None:
    turns = build_turns(segments(), {"spk_0": "agent", "spk_1": "agent"})
    assert [t.speaker for t in turns] == ["agent", "agent"]  # the 3 s gap before 9000 splits
    assert turns[0].end_ms == 6000


def test_caller_speaking_over_the_agent_is_a_barge_in() -> None:
    turns = build_turns(
        [
            LabelledSegment("spk_0", 0, 4000, "long explanation"),
            LabelledSegment("spk_1", 3000, 5000, "stop"),
        ],
        {"spk_0": "agent", "spk_1": "caller"},
    )
    assert [t.is_barge_in for t in turns] == [False, True]


def test_segment_round_trip_through_json_dict() -> None:
    s = LabelledSegment("spk_1", 10, 20, "x", "2")
    assert LabelledSegment.from_dict(s.to_dict()) == s
    assert LabelledSegment.from_dict(
        {"label": "spk_0", "start_ms": 1, "end_ms": 2, "text": "t"}
    ) == (LabelledSegment("spk_0", 1, 2, "t", None))
