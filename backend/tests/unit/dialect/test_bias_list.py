"""T-FR-DI-6: bias_list suggestions from frequently missed domain words."""

from __future__ import annotations

from pareeksha.dialect.report import ResultRow, aggregate, bias_suggestions, top_errors


def row(
    ref: str,
    hyp: str,
    terms: tuple[str, ...] = (),
    subs: tuple[tuple[str, str], ...] = (),
) -> ResultRow:
    return ResultRow(
        dialect="d",
        condition="c",
        engine="e",
        speaker_id="s",
        ref_norm=ref,
        hyp_norm=hyp,
        entity_total=0,
        entity_correct=0,
        intent_preserved=None,
        substitutions=subs,
        domain_terms=terms,
    )


def test_terms_missed_at_least_twice_are_suggested_most_frequent_first() -> None:
    rows = [
        row("your neft failed", "your nef failed", ("NEFT",)),
        row("neft utr again", "nef utr again", ("NEFT", "UTR")),
        row("neft pending", "nef pending", ("NEFT",)),
        row("utr missing", "utr missing", ("UTR",)),  # heard correctly
        row("kantu due", "kanthu due", ("kantu",)),  # missed once only
    ]
    assert bias_suggestions(rows) == ["neft"]


def test_reference_words_that_keep_being_misrecognised_are_added() -> None:
    subs = (("ಕಂತು", "ಕಾಂತು"),)
    rows = [row("x", "y", subs=subs) for _ in range(3)] + [row("x", "y", subs=(("ಬಾಕಿ", ""),))]
    assert bias_suggestions(rows) == ["ಕಂತು"]  # 3 misses; ಬಾಕಿ only once


def test_numbers_are_never_suggested() -> None:
    rows = [row("pay 5000 now", "pay 500 now", ("5000",)) for _ in range(3)]
    assert bias_suggestions(rows) == []


def test_top_errors_counts_substitutions_and_deletions() -> None:
    rows = [
        row("a", "b", subs=(("ಕಂತು", "ಕಾಂತು"), ("ಬಾಕಿ", ""))),
        row("a", "b", subs=(("ಕಂತು", "ಕಾಂತು"),)),
        row("a", "b", subs=(("", "extra"),)),  # insertion: not a misrecognised reference word
    ]
    assert top_errors(rows) == [
        {"ref": "ಕಂತು", "hyp": "ಕಾಂತು", "count": 2},
        {"ref": "ಬಾಕಿ", "hyp": "", "count": 1},
    ]


def test_aggregate_exposes_both_lists() -> None:
    rows = [row("neft x", "nef x", ("NEFT",), (("neft", "nef"),)) for _ in range(3)]
    result = aggregate(rows, resamples=20)
    assert result.bias_suggestions == ["neft"]
    assert result.top_errors[0] == {"ref": "neft", "hyp": "nef", "count": 3}
