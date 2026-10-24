"""Deterministic call metrics (docs/08 section 6).

All functions are pure and work on turn-level timing (`Turn.start_ms/end_ms`), so they
apply equally to simulated and uploaded calls. Times are milliseconds from call start
unless a `ws_open_ms` is given.

Conventions where the spec leaves room:
  * Response latency of caller turn i = next agent turn start - caller turn end. Pairs
    where the agent started before the caller finished (negative gap) are excluded from
    the percentiles and counted in `agent_overlap_starts`.
  * Percentiles use linear interpolation (numpy default).
  * Barge-in: attempts = caller turns flagged `is_barge_in`. The agent turn overlapping
    the caller's start is the one being interrupted; it is honoured when that turn ends
    <= 1500 ms after the caller started AND the agent stays silent >= 300 ms after it
    (next agent turn starts >= 300 ms later, or there is none). A flagged turn with no
    agent speech to interrupt counts as honoured. Agent stop time = interrupted agent
    turn end - caller start.
  * Silence gap = time between merged speech intervals (either speaker) > 2000 ms; the
    lead-in before the first turn and the tail after the last turn are not gaps.
  * Repeated utterances only consider agent turns of >= `min_words` words (default 3) so
    that "Haan ji" or "Okay" are not counted as a loop.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field

from rapidfuzz import fuzz

from .numbers import normalize_numbers
from .types import Turn, as_turns

SILENCE_GAP_MS = 2000
BARGE_IN_WINDOW_MS = 1500
BARGE_IN_SILENCE_MS = 300
REPEAT_SIMILARITY = 0.9


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolated percentile (p in 0..100). None for an empty sequence."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    k = (len(xs) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return float(xs[lo] + (xs[hi] - xs[lo]) * (k - lo))


def _merge(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


# -- text normalisation (used for repeats and WER) ------------------------------

_PUNCT = re.compile(r"[^\w\sऀ-ॿಀ-೿]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Lowercase, canonical number digits, punctuation stripped, single spaces."""
    t = normalize_numbers(text).lower()
    t = _PUNCT.sub(" ", t)
    return " ".join(t.split())


# -- individual metrics ------------------------------------------------------------------


def response_latencies(turns: Sequence[Turn]) -> tuple[list[int], int]:
    """(latencies in ms, count of negative/overlapping pairs) for caller -> next agent turn."""
    lat, overlaps = [], 0
    for i, t in enumerate(turns):
        if t.speaker != "caller":
            continue
        nxt = turns[i + 1] if i + 1 < len(turns) else None
        if nxt is None or nxt.speaker != "agent":
            continue  # only a caller turn immediately answered by the agent counts
        gap = nxt.start_ms - t.end_ms
        if gap < 0:
            overlaps += 1
        else:
            lat.append(gap)
    return lat, overlaps


def first_greeting_latency(turns: Sequence[Turn], ws_open_ms: int = 0) -> int | None:
    first = next((t for t in turns if t.speaker == "agent"), None)
    return None if first is None else max(0, first.start_ms - ws_open_ms)


def barge_in_stats(turns: Sequence[Turn]) -> tuple[int, int, list[int]]:
    """(attempts, honoured, agent_stop_times_ms)."""
    attempts = honoured = 0
    stops: list[int] = []
    agents = [t for t in turns if t.speaker == "agent"]
    for c in turns:
        if c.speaker != "caller" or not c.is_barge_in:
            continue
        attempts += 1
        interrupted = next((a for a in agents if a.start_ms < c.start_ms < a.end_ms), None)
        if interrupted is None:
            honoured += 1
            continue
        stop = max(0, interrupted.end_ms - c.start_ms)
        stops.append(stop)
        nxt = next(
            (a for a in agents if a.start_ms >= interrupted.end_ms and a.idx != interrupted.idx),
            None,
        )
        silent_long_enough = nxt is None or nxt.start_ms - interrupted.end_ms >= BARGE_IN_SILENCE_MS
        if stop <= BARGE_IN_WINDOW_MS and silent_long_enough:
            honoured += 1
    return attempts, honoured, stops


def silence_gaps(turns: Sequence[Turn], threshold_ms: int = SILENCE_GAP_MS) -> list[int]:
    merged = _merge((t.start_ms, t.end_ms) for t in turns)
    return [
        merged[i + 1][0] - merged[i][1]
        for i in range(len(merged) - 1)
        if merged[i + 1][0] - merged[i][1] > threshold_ms
    ]


def talk_ratio(turns: Sequence[Turn]) -> float | None:
    def total(speaker: str) -> int:
        return sum(
            e - s for s, e in _merge((t.start_ms, t.end_ms) for t in turns if t.speaker == speaker)
        )

    a, c = total("agent"), total("caller")
    return None if a + c == 0 else a / (a + c)


def find_repeats(
    turns: Sequence[Turn], threshold: float = REPEAT_SIMILARITY, min_words: int = 3
) -> dict[int, int]:
    """Map repeated agent turn idx -> idx of the earliest turn it repeats."""
    seen: list[tuple[int, str]] = []
    repeats: dict[int, int] = {}
    for t in turns:
        if t.speaker != "agent":
            continue
        norm = normalize_text(t.text)
        if len(norm.split()) < min_words:
            continue
        for idx, prev in seen:
            if fuzz.ratio(norm, prev) / 100.0 >= threshold:
                repeats[t.idx] = idx
                break
        else:
            seen.append((t.idx, norm))
    return repeats


def _edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str) -> float | None:
    """Word error rate on normalised text; None if the reference has no words."""
    ref, hyp = normalize_text(reference).split(), normalize_text(hypothesis).split()
    if not ref:
        return None
    return _edit_distance(ref, hyp) / len(ref)


def caller_wer(turns: Sequence[Turn]) -> tuple[float | None, int]:
    """Pooled WER over caller turns with both ground truth and agent_heard text.

    Returns (wer, number of turns used). Pooled = total word errors / total reference words.
    """
    errors = words = used = 0
    for t in turns:
        if t.speaker != "caller" or t.ground_truth_text is None or t.agent_heard_text is None:
            continue
        ref = normalize_text(t.ground_truth_text).split()
        if not ref:
            continue
        hyp = normalize_text(t.agent_heard_text).split()
        errors += _edit_distance(ref, hyp)
        words += len(ref)
        used += 1
    return (errors / words if words else None), used


# -- aggregate -------------------------------------------------------------------------


@dataclass
class CallMetrics:
    response_latency_p50_ms: float | None = None
    response_latency_p95_ms: float | None = None
    response_latency_count: int = 0
    agent_overlap_starts: int = 0
    first_greeting_latency_ms: int | None = None
    barge_in_attempts: int = 0
    barge_in_honoured: int = 0
    barge_in_honoured_rate: float | None = None
    agent_stop_time_p50_ms: float | None = None
    silence_gaps_over_2s: int = 0
    agent_talk_ratio: float | None = None
    repeated_utterances: int = 0
    caller_wer: float | None = None
    caller_wer_turns: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def compute_metrics(turns_in: Iterable, ws_open_ms: int = 0) -> CallMetrics:
    turns = as_turns(turns_in)
    lat, overlaps = response_latencies(turns)
    attempts, honoured, stops = barge_in_stats(turns)
    w, w_turns = caller_wer(turns)
    return CallMetrics(
        response_latency_p50_ms=percentile(lat, 50),
        response_latency_p95_ms=percentile(lat, 95),
        response_latency_count=len(lat),
        agent_overlap_starts=overlaps,
        first_greeting_latency_ms=first_greeting_latency(turns, ws_open_ms),
        barge_in_attempts=attempts,
        barge_in_honoured=honoured,
        barge_in_honoured_rate=(honoured / attempts) if attempts else None,
        agent_stop_time_p50_ms=percentile(stops, 50),
        silence_gaps_over_2s=len(silence_gaps(turns)),
        agent_talk_ratio=talk_ratio(turns),
        repeated_utterances=len(find_repeats(turns)),
        caller_wer=w,
        caller_wer_turns=w_turns,
    )
