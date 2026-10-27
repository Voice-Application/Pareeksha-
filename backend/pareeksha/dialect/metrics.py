"""WER, CER, substitutions and entity accuracy on normalised text (FR-DI-3)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from pareeksha.dialect.normalize import normalize
from pareeksha.evaluation.numbers import extract_numbers


@dataclass(frozen=True)
class Alignment:
    """Edit distance plus the aligned operations (reference word, hypothesis word)."""

    distance: int
    ref_len: int
    #: ``(ref, hyp)`` per error; ``hyp == ""`` is a deletion, ``ref == ""`` an insertion.
    errors: list[tuple[str, str]] = field(default_factory=list)


def align(ref: Sequence[str], hyp: Sequence[str]) -> Alignment:
    """Levenshtein alignment with back-trace (substitution cost 1, ties prefer substitution)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(
                d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1])
            )
    errors: list[tuple[str, str]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                errors.append((ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            errors.append((ref[i - 1], ""))
            i -= 1
        else:
            errors.append(("", hyp[j - 1]))
            j -= 1
    errors.reverse()
    return Alignment(d[n][m], n, errors)


def edit_distance(ref: Sequence[str], hyp: Sequence[str]) -> int:
    return align(ref, hyp).distance


def word_edits(ref_norm: str, hyp_norm: str) -> tuple[int, int]:
    """``(word edits, reference words)`` for already-normalised texts."""
    r = ref_norm.split()
    return edit_distance(r, hyp_norm.split()), len(r)


def char_edits(ref_norm: str, hyp_norm: str) -> tuple[int, int]:
    """``(character edits, reference characters)``; spaces are ignored (CER of Indic scripts
    should not depend on how an engine splits words)."""
    r, h = ref_norm.replace(" ", ""), hyp_norm.replace(" ", "")
    return edit_distance(r, h), len(r)


@dataclass(frozen=True)
class ClipScores:
    ref_norm: str
    hyp_norm: str
    wer: float
    cer: float
    entity_total: int
    entity_correct: int
    substitutions: list[tuple[str, str]]


def _number_tokens(text: str) -> list[str]:
    return [n.canonical for n in extract_numbers(text)]


def entity_hits(
    ref_norm: str, hyp_norm: str, domain_terms: Sequence[str]
) -> tuple[list[str], list[str]]:
    """``(correct, missed)`` entities of the reference: numbers and amounts by value (multiset),
    domain terms / names as whole-word phrases in the hypothesis."""
    hyp_numbers = Counter(_number_tokens(hyp_norm))
    hyp_tokens = hyp_norm.split()
    correct: list[str] = []
    missed: list[str] = []
    for num in _number_tokens(ref_norm):
        if hyp_numbers[num] > 0:
            hyp_numbers[num] -= 1
            correct.append(num)
        else:
            missed.append(num)
    for term in dict.fromkeys(t for t in (normalize(x) for x in domain_terms) if t):
        words = term.split()
        found = any(
            hyp_tokens[i : i + len(words)] == words for i in range(len(hyp_tokens) - len(words) + 1)
        )
        (correct if found else missed).append(term)
    return correct, missed


def score_clip(reference: str, hypothesis: str, domain_terms: Sequence[str] = ()) -> ClipScores:
    """Normalise both texts and compute WER, CER, entity counts and word-level errors."""
    ref_norm, hyp_norm = normalize(reference), normalize(hypothesis)
    ref_words = ref_norm.split()
    alignment = align(ref_words, hyp_norm.split())
    w = alignment.distance / len(ref_words) if ref_words else (1.0 if hyp_norm else 0.0)
    c_edits, c_len = char_edits(ref_norm, hyp_norm)
    c = c_edits / c_len if c_len else (1.0 if hyp_norm else 0.0)
    correct, missed = entity_hits(ref_norm, hyp_norm, domain_terms)
    return ClipScores(
        ref_norm=ref_norm,
        hyp_norm=hyp_norm,
        wer=round(w, 4),
        cer=round(c, 4),
        entity_total=len(correct) + len(missed),
        entity_correct=len(correct),
        substitutions=alignment.errors,
    )
