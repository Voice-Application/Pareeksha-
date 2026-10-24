"""Deterministic checks producing `deterministic_checks` rows (docs/05, docs/08).

check_type values (schema.sql CHECK): disclosure_present, forbidden_absent,
language_match, tool_calls_expected, no_loop, amount_confirmed.
`passed=None` means "not applicable" (nothing to verify).

Matching rules (text comes from the platform STT, so matching is tolerant):
  * `regex` on a disclosure / forbidden phrase wins when present (case-insensitive search).
  * otherwise the normalised phrase must be a substring of the normalised turn text, or,
    for phrases of >= 12 characters, rapidfuzz partial_ratio >= 85 (disclosures) / 92
    (forbidden). Negation is not understood: "we will not threaten you" still contains
    "threaten". Forbidden phrases should therefore be specific.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from rapidfuzz import fuzz

from .metrics import find_repeats, normalize_text
from .numbers import ParsedNumber, extract_numbers, parse_number
from .types import CheckResult, Disclosure, ForbiddenPhrase, ToolCall, Turn, as_turns

DISCLOSURE_FUZZY = 85
FORBIDDEN_FUZZY = 92
FUZZY_MIN_CHARS = 12


def _matches(phrase: str, regex: str | None, text: str, fuzzy: int) -> bool:
    if regex:
        return re.search(regex, text, re.IGNORECASE) is not None
    p, t = normalize_text(phrase), normalize_text(text)
    if not p:
        return False
    if p in t:
        return True
    return len(p) >= FUZZY_MIN_CHARS and fuzz.partial_ratio(p, t) >= fuzzy


# -- disclosure_present ------------------------------------------------------------------


def check_disclosures(
    turns: Iterable, disclosures: Iterable[Mapping | Disclosure]
) -> list[CheckResult]:
    agent_turns = [t for t in as_turns(turns) if t.speaker == "agent"]
    results = []
    for d in disclosures:
        d = d if isinstance(d, Disclosure) else Disclosure.from_dict(d)
        scope = agent_turns if d.within_turns is None else agent_turns[: d.within_turns]
        hits = [t.idx for t in scope if _matches(d.text, d.regex, t.text, DISCLOSURE_FUZZY)]
        if hits:
            results.append(
                CheckResult(
                    "disclosure_present",
                    d.id,
                    True,
                    d.must_pass,
                    (hits[0],),
                    f"Disclosure given in turn {hits[0]}",
                )
            )
        else:
            where = (
                "the call" if d.within_turns is None else f"the first {d.within_turns} agent turns"
            )
            results.append(
                CheckResult(
                    "disclosure_present",
                    d.id,
                    False,
                    d.must_pass,
                    tuple(t.idx for t in scope),
                    f"No '{d.id}' disclosure in {where}",
                )
            )
    return results


# -- forbidden_absent -------------------------------------------------------------------


def check_forbidden(
    turns: Iterable, phrases: Iterable[Mapping | ForbiddenPhrase]
) -> list[CheckResult]:
    agent_turns = [t for t in as_turns(turns) if t.speaker == "agent"]
    results = []
    for p in phrases:
        p = p if isinstance(p, ForbiddenPhrase) else ForbiddenPhrase.from_dict(p)
        hits = [t.idx for t in agent_turns if _matches(p.text, p.regex, t.text, FORBIDDEN_FUZZY)]
        if hits:
            results.append(
                CheckResult(
                    "forbidden_absent",
                    p.id,
                    False,
                    p.must_pass,
                    tuple(hits),
                    f"Forbidden phrase '{p.id}' said in turn(s) {hits}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "forbidden_absent",
                    p.id,
                    True,
                    p.must_pass,
                    (),
                    "Phrase never said by the agent",
                )
            )
    return results


# -- language_match ---------------------------------------------------------------------

_SCRIPTS = {
    "kn": re.compile(r"[ಀ-೿]"),
    "hi": re.compile(r"[ऀ-ॿ]"),
    "en": re.compile(r"[A-Za-z]"),
}


def _dominant_script(text: str) -> str | None:
    counts = {k: len(r.findall(text)) for k, r in _SCRIPTS.items()}
    total = sum(counts.values())
    if total < 3:
        return None
    return max(counts, key=lambda k: counts[k])


def _base(lang: str) -> str:
    return lang.split("-")[0].lower()


def check_language(
    turns: Iterable,
    expected: str,
    allowed: Sequence[str] = (),
    max_mismatch_ratio: float = 0.2,
    must_pass: bool = False,
) -> CheckResult:
    """Agent replies should be in the caller's language.

    A turn's language is its `language_detected` when provided, else its dominant script
    (Kannada and Devanagari scripts identify kn / hi; Latin script is treated as English).
    Agent turns with fewer than 3 letters, or Latin-only turns of < 4 words, are skipped
    so "OK sir" does not count as switching language. Fails when more than
    `max_mismatch_ratio` of the eligible turns are in a language outside {expected, allowed}.
    """
    ok = {_base(expected)} | {_base(a) for a in allowed}
    eligible, bad = [], []
    for t in as_turns(turns):
        if t.speaker != "agent":
            continue
        lang = _base(t.language_detected) if t.language_detected else _dominant_script(t.text)
        if lang is None:
            continue
        if lang == "en" and not t.language_detected and len(t.text.split()) < 4:
            continue
        eligible.append(t.idx)
        if lang not in ok:
            bad.append(t.idx)
    if not eligible:
        return CheckResult(
            "language_match",
            expected,
            None,
            must_pass,
            (),
            "No agent turns long enough to classify",
        )
    ratio = len(bad) / len(eligible)
    passed = ratio <= max_mismatch_ratio
    return CheckResult(
        "language_match",
        expected,
        passed,
        must_pass,
        tuple(bad),
        f"{len(bad)}/{len(eligible)} agent turns not in {sorted(ok)}",
    )


# -- no_loop ------------------------------------------------------------------------------


def check_no_loop(
    turns: Iterable, max_occurrences: int = 3, must_pass: bool = False
) -> CheckResult:
    """Fail when one agent utterance (similarity >= 0.9) occurs `max_occurrences`+ times."""
    ts = as_turns(turns)
    if not any(t.speaker == "agent" for t in ts):
        return CheckResult("no_loop", "agent_repeats", None, must_pass, (), "No agent turns")
    clusters: dict[int, list[int]] = {}
    for rep, first in find_repeats(ts).items():
        clusters.setdefault(first, [first]).append(rep)
    worst = max(clusters.values(), key=len, default=[])
    if len(worst) >= max_occurrences:
        return CheckResult(
            "no_loop",
            "agent_repeats",
            False,
            must_pass,
            tuple(sorted(worst)),
            f"Agent said nearly the same thing {len(worst)} times",
        )
    return CheckResult(
        "no_loop",
        "agent_repeats",
        True,
        must_pass,
        tuple(sorted(worst)),
        "No repeated utterance loop",
    )


# -- tool_calls_expected ------------------------------------------------------------------


def _value_eq(expected: Any, actual: Any) -> bool:
    if expected == actual:
        return True
    pe = parse_number(expected) if isinstance(expected, str) else expected
    pa = parse_number(actual) if isinstance(actual, str) else actual
    if (
        isinstance(pe, (int, float))
        and isinstance(pa, (int, float))
        and not isinstance(pe, bool)
        and not isinstance(pa, bool)
    ):
        return float(pe) == float(pa)
    if isinstance(expected, str) and isinstance(actual, str):
        return normalize_text(expected) == normalize_text(actual)
    return False


def check_tool_calls(
    expected: Iterable[Mapping] | None, actual: Iterable[Mapping | ToolCall] | None
) -> list[CheckResult]:
    """Each expected `{name, args, order?}` must appear in `actual` with matching args.

    Args are compared as a subset (extra actual args are fine); numbers compare by value.
    If `order` is given on several expected calls, their matches must appear in that order.
    `actual=None` (tool trace unavailable) yields passed=None for every expected call.
    """
    expected = list(expected or [])
    if not expected:
        return []
    if actual is None:
        return [
            CheckResult(
                "tool_calls_expected",
                e["name"],
                None,
                True,
                (),
                "Tool trace not available",
            )
            for e in expected
        ]
    calls = [c if isinstance(c, ToolCall) else ToolCall.from_dict(c) for c in actual]
    results: list[CheckResult] = []
    positions: list[tuple[int, int, str]] = []  # (order, position in actual, name)
    used: set[int] = set()
    for n, exp in enumerate(expected):
        want = exp.get("args") or {}
        match = next(
            (
                i
                for i, c in enumerate(calls)
                if i not in used
                and c.name == exp["name"]
                and all(k in c.args and _value_eq(v, c.args[k]) for k, v in want.items())
            ),
            None,
        )
        key = (
            exp["name"]
            if sum(1 for e in expected if e["name"] == exp["name"]) == 1
            else f"{exp['name']}#{n + 1}"
        )
        if match is None:
            same_name = [c for c in calls if c.name == exp["name"]]
            why = (
                f"called with different arguments: {same_name[0].args}"
                if same_name
                else "never called"
            )
            results.append(
                CheckResult(
                    "tool_calls_expected",
                    key,
                    False,
                    True,
                    (),
                    f"Expected {exp['name']}({want}) {why}",
                )
            )
            continue
        used.add(match)
        match_turn = calls[match].turn_idx
        ev: tuple[int, ...] = (match_turn,) if match_turn is not None else ()
        results.append(
            CheckResult(
                "tool_calls_expected",
                key,
                True,
                True,
                ev,
                f"{exp['name']} called as expected",
            )
        )
        if exp.get("order") is not None:
            positions.append((int(exp["order"]), match, key))
    ordered = sorted(positions)
    for (_, p1, k1), (_, p2, k2) in itertools.pairwise(ordered):
        if p2 < p1:
            idx = next(i for i, r in enumerate(results) if r.check_key == k2)
            results[idx] = CheckResult(
                "tool_calls_expected",
                k2,
                False,
                True,
                results[idx].evidence_turns,
                f"{k2} was called before {k1} but should come after",
            )
    return results


# -- amount_confirmed -------------------------------------------------------------------

_YEAR = range(1900, 2101)


def _agent_amounts(turn: Turn) -> list[ParsedNumber]:
    """Numbers in an agent turn that plausibly state money."""
    out = []
    for n in extract_numbers(turn.text):
        if n.currency or (
            1000 <= n.value < 10**8 and not (float(n.value).is_integer() and int(n.value) in _YEAR)
        ):
            out.append(n)
    return out


def check_amounts(
    turns: Iterable, expected_amounts: Mapping[str, int | float | str]
) -> list[CheckResult]:
    """Did the agent read back each expected amount correctly?

    `expected_amounts` maps a key (e.g. "emi_amount") to the true value from scenario
    fixtures. Agent amounts are currency-marked numbers plus bare numbers 1,000..99,999,999
    (excluding years). An agent amount that equals none of the expected values counts as
    wrong. Per key:
      * passed=None  - the agent never stated any amount (nothing was confirmed)
      * passed=True  - the agent stated the expected value and its last stated amount
                       in that turn set is not a wrong one (self-corrections pass)
      * passed=False - the agent stated a wrong amount and its last amount statement is wrong,
                       or never stated the expected value
    """
    ts = [t for t in as_turns(turns) if t.speaker == "agent"]
    truth: dict[str, float] = {}
    for k, v in expected_amounts.items():
        val = parse_number(v) if isinstance(v, str) else v
        if val is not None:
            truth[k] = float(val)
    known = set(truth.values())
    stated = [(t.idx, float(n.value)) for t in ts for n in _agent_amounts(t)]
    results = []
    for key, want in truth.items():
        if not stated:
            results.append(
                CheckResult(
                    "amount_confirmed",
                    key,
                    None,
                    True,
                    (),
                    "Agent never stated an amount",
                )
            )
            continue
        right = [i for i, v in stated if v == want]
        wrong = [(i, v) for i, v in stated if v not in known]
        last_val = stated[-1][1]
        if wrong and (not right or last_val not in known):
            i, v = wrong[-1]
            results.append(
                CheckResult(
                    "amount_confirmed",
                    key,
                    False,
                    True,
                    tuple(sorted({i, *right})),
                    f"Expected {want:g}; agent confirmed {v:g}",
                )
            )
        elif right:
            results.append(
                CheckResult(
                    "amount_confirmed",
                    key,
                    True,
                    True,
                    tuple(right[:3]),
                    f"Agent stated {want:g} correctly",
                )
            )
        else:
            results.append(
                CheckResult(
                    "amount_confirmed",
                    key,
                    None,
                    True,
                    (),
                    f"Agent stated other known amounts but not {want:g}",
                )
            )
    return results


# -- orchestration ------------------------------------------------------------------------


def run_checks(
    turns: Iterable,
    *,
    disclosures: Iterable = (),
    forbidden: Iterable = (),
    expected_language: str | None = None,
    allowed_languages: Sequence[str] = (),
    expected_tool_calls: Iterable[Mapping] | None = None,
    tool_calls: Iterable | None = None,
    expected_amounts: Mapping[str, Any] | None = None,
) -> list[CheckResult]:
    ts = as_turns(turns)
    out: list[CheckResult] = []
    out += check_disclosures(ts, disclosures)
    out += check_forbidden(ts, forbidden)
    if expected_language:
        out.append(check_language(ts, expected_language, allowed_languages))
    out.append(check_no_loop(ts))
    out += check_tool_calls(expected_tool_calls, None if tool_calls is None else list(tool_calls))
    if expected_amounts:
        out += check_amounts(ts, expected_amounts)
    return out
