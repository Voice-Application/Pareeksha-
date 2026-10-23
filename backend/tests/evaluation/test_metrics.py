import pytest

from pareeksha.evaluation.metrics import (
    barge_in_stats,
    caller_wer,
    compute_metrics,
    find_repeats,
    percentile,
    silence_gaps,
    talk_ratio,
    wer,
)
from pareeksha.evaluation.types import Turn


def T(idx, speaker, s, e, text="", **kw):
    return Turn(idx=idx, speaker=speaker, start_ms=s, end_ms=e, text=text, **kw)


def test_percentile_linear_interpolation():
    assert percentile([], 50) is None
    assert percentile([7], 95) == 7
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([0, 100], 95) == 95
    assert percentile(list(range(1, 101)), 95) == pytest.approx(95.05)


def test_response_latency_and_greeting():
    turns = [
        T(0, "agent", 800, 3000, "Namaste, welcome"),
        T(1, "caller", 3500, 5000),
        T(2, "agent", 5600, 8000),  # 600 ms
        T(3, "caller", 8500, 9000),
        T(4, "agent", 10500, 12000),  # 1500 ms
        T(5, "caller", 12500, 13000),
        T(6, "agent", 12900, 14000),  # started before caller ended: excluded
    ]
    m = compute_metrics(turns, ws_open_ms=300)
    assert m.first_greeting_latency_ms == 500
    assert m.response_latency_count == 2
    assert m.response_latency_p50_ms == 1050
    assert m.response_latency_p95_ms == pytest.approx(1455)
    assert m.agent_overlap_starts == 1


def test_latency_ignores_caller_followed_by_caller():
    turns = [
        T(0, "caller", 0, 1000),
        T(1, "caller", 1200, 2000),
        T(2, "agent", 2500, 3000),
    ]
    m = compute_metrics(turns)
    assert m.response_latency_count == 1 and m.response_latency_p50_ms == 500


def test_empty_call():
    m = compute_metrics([])
    assert m.response_latency_p50_ms is None and m.first_greeting_latency_ms is None
    assert m.barge_in_attempts == 0 and m.barge_in_honoured_rate is None
    assert m.agent_talk_ratio is None and m.silence_gaps_over_2s == 0


def test_barge_in_honoured_and_ignored():
    # Variant A: agent turn ends 800 ms after caller began, next agent speech 1500 ms later
    a = [
        T(0, "agent", 0, 2800),
        T(1, "caller", 2000, 3500, is_barge_in=True),
        T(2, "agent", 4300, 6000),
    ]
    attempts, honoured, stops = barge_in_stats(a)
    assert (attempts, honoured, stops) == (1, 1, [800])
    # Variant B: agent talks over the caller for 4 s -> not honoured
    b = [T(0, "agent", 0, 6000), T(1, "caller", 2000, 3500, is_barge_in=True)]
    assert barge_in_stats(b) == (1, 0, [4000])
    # Variant C: agent stops in time but resumes after only 100 ms -> not honoured
    c = [
        T(0, "agent", 0, 2500),
        T(1, "caller", 2000, 3500, is_barge_in=True),
        T(2, "agent", 2600, 4000),
    ]
    assert barge_in_stats(c)[1] == 0
    # Variant D: flagged but agent was not speaking -> counts as honoured
    d = [T(0, "agent", 0, 1000), T(1, "caller", 2000, 3000, is_barge_in=True)]
    assert barge_in_stats(d) == (1, 1, [])


def test_barge_in_rate_in_metrics():
    turns = [
        T(0, "agent", 0, 2800),
        T(1, "caller", 2000, 3500, is_barge_in=True),
        T(2, "agent", 4300, 9000),
        T(3, "caller", 5000, 6000, is_barge_in=True),
    ]
    m = compute_metrics(turns)
    assert (m.barge_in_attempts, m.barge_in_honoured) == (2, 1)
    assert m.barge_in_honoured_rate == 0.5


def test_silence_gaps_merge_overlap_and_exclude_edges():
    turns = [
        T(0, "agent", 5000, 6000),  # lead-in before 5000 is not a gap
        T(1, "caller", 5800, 7000),  # overlap merges
        T(2, "agent", 9500, 10000),  # 2500 ms gap -> counts
        T(3, "caller", 11900, 12000),  # 1900 ms gap -> no
        T(4, "agent", 14500, 15000),  # 2500 ms gap -> counts
    ]  # tail after 15000 never counts
    assert silence_gaps(turns) == [2500, 2500]
    assert (
        silence_gaps([T(0, "agent", 0, 1000), T(1, "caller", 3000, 4000)]) == []
    )  # exactly 2000 ms


def test_talk_ratio():
    turns = [T(0, "agent", 0, 6000), T(1, "caller", 6000, 10000)]
    assert talk_ratio(turns) == pytest.approx(0.6)
    overlap = [
        T(0, "agent", 0, 4000),
        T(1, "agent", 2000, 6000),
        T(2, "caller", 6000, 10000),
    ]
    assert talk_ratio(overlap) == pytest.approx(0.6)  # agent overlap not double counted
    assert talk_ratio([T(0, "agent", 5, 5)]) is None


def test_repeated_utterances():
    turns = [
        T(0, "agent", 0, 1, "Please confirm your EMI amount of four thousand rupees."),
        T(1, "caller", 2, 3, "ok"),
        T(
            2, "agent", 4, 5, "Please confirm your EMI amount of 4000 rupees"
        ),  # same after normalisation
        T(3, "agent", 6, 7, "Okay"),  # too short
        T(4, "agent", 8, 9, "Okay"),
        T(5, "agent", 10, 11, "Thank you for calling, goodbye."),
    ]
    assert find_repeats(turns) == {2: 0}
    assert compute_metrics(turns).repeated_utterances == 1


def test_wer_values():
    assert wer("naalku saavira rupayi", "naalku saavira rupayi") == 0
    assert wer("a b c d", "a x c") == pytest.approx(0.5)  # 1 sub + 1 del of 4
    assert wer("", "anything") is None
    # digits and words compare equal after number normalisation
    assert wer("pay four thousand", "pay 4000") == 0
    assert wer("चार हज़ार", "4000") == 0


def test_caller_wer_is_pooled():
    turns = [
        T(
            0,
            "caller",
            0,
            1,
            ground_truth_text="one two three four",
            agent_heard_text="one two three four",
        ),
        T(
            1,
            "caller",
            2,
            3,
            ground_truth_text="red blue",
            agent_heard_text="green blue",
        ),
        T(2, "caller", 4, 5),  # no ground truth
        T(
            3, "agent", 6, 7, ground_truth_text="x", agent_heard_text="y"
        ),  # agent turns ignored
    ]
    w, used = caller_wer(turns)
    assert used == 2 and w == pytest.approx(1 / 6)


def test_as_turn_accepts_mappings():
    m = compute_metrics(
        [
            {
                "idx": 1,
                "speaker": "caller",
                "start_ms": 0,
                "end_ms": 1000,
                "text": "hi",
            },
            {
                "idx": 2,
                "speaker": "agent",
                "start_ms": 1400,
                "end_ms": 2000,
                "text": "hello",
            },
        ]
    )
    assert m.response_latency_p50_ms == 400
