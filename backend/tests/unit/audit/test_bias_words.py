"""Agent bias lists are sent to the vendor as single words (Gnani 400s on phrases)."""

from __future__ import annotations

from pareeksha.audit.pipeline import bias_words, primary_language


def test_phrases_are_split_and_deduplicated_in_order() -> None:
    assert bias_words(["EMI", "Shakti Finance", "किस्त", "EMI due", "  UPI  "]) == [
        "EMI",
        "Shakti",
        "Finance",
        "किस्त",
        "due",
        "UPI",
    ]


def test_empty_bias_list_means_no_bias_words() -> None:
    assert bias_words(None) is None
    assert bias_words([]) is None
    assert bias_words(["  ", ""]) is None


def test_primary_language_is_the_first_tag() -> None:
    assert primary_language("kn-IN, en-IN") == "kn-IN"
    assert primary_language("hi-IN") == "hi-IN"
    assert primary_language("") == ""
