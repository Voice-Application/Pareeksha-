"""T-FR-DI-3: normalised WER / CER / entity accuracy on known pairs."""

from __future__ import annotations

import pytest

from pareeksha.dialect.metrics import align, entity_hits, score_clip
from pareeksha.dialect.normalize import normalize


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("आपकी EMI पाँच हज़ार रुपये है।", "आपकी ईएमआई 5000 रुपये है"),  # number words, loanword script
        ("ನಿಮ್ಮ ಇಎಂಐ ಐದು ಸಾವಿರ ರೂಪಾಯಿ", "ನಿಮ್ಮ EMI ೫೦೦೦ ರೂಪಾಯಿ."),  # Kannada digits
        ("दो लाख पचास हज़ार", "250000"),  # lakh grouping
        ("ಎರಡು ಲಕ್ಷ ಐವತ್ತು ಸಾವಿರ", "2,50,000"),
        ("Bank", "ಬ್ಯಾಂಕ್"),
        ("ज़रूर", "जरूर"),  # nukta
        ("पाँच सौ रुपये", "500 रुपए"),  # accepted spelling variants
        ("ಐದು ನೂರು ರೂಪಾಯಿ", "500 ರುಪಾಯಿ"),
        ("ನಿಮ್ಮ‍ ಲೋನ್", "ನಿಮ್ಮ ಲೋನ್"),  # zero-width joiner
    ],
)
def test_equivalent_spellings_normalise_identically(a: str, b: str) -> None:
    assert normalize(a) == normalize(b)


def test_kannada_vowel_signs_survive_punctuation_stripping() -> None:
    assert normalize("ಕಂತು, ಕಟ್ಟಿ!") == "ಕಂತು ಕಟ್ಟಿ"


def test_wer_cer_on_a_known_pair() -> None:
    # 5 reference words, one substitution (ಕಂತು -> ಕಾಂತು): WER 0.2
    s = score_clip("ನಿಮ್ಮ ಇಎಂಐ ಐದು ಸಾವಿರ ರೂಪಾಯಿ ಕಂತು", "ನಿಮ್ಮ EMI 5000 ರೂಪಾಯಿ ಕಾಂತು")
    assert s.ref_norm == "ನಿಮ್ಮ emi 5000 rupees ಕಂತು"
    assert s.wer == pytest.approx(0.2)
    assert 0 < s.cer < s.wer
    assert s.substitutions == [("ಕಂತು", "ಕಾಂತು")]


def test_wer_counts_deletions_insertions_and_can_exceed_one() -> None:
    assert score_clip("a b c d", "a c d").wer == pytest.approx(0.25)  # one deletion
    assert score_clip("a b", "a b c d").wer == pytest.approx(1.0)  # two insertions
    assert score_clip("a", "x y z").wer == pytest.approx(3.0)
    assert score_clip("hello", "hello").wer == 0.0
    assert score_clip("hello", "").wer == 1.0


def test_alignment_labels_each_error_kind() -> None:
    a = align(["a", "b", "c"], ["a", "x", "c", "d"])
    assert a.distance == 2
    assert a.errors == [("b", "x"), ("", "d")]
    assert align(["a", "b"], ["b"]).errors == [("a", "")]


def test_entity_accuracy_counts_numbers_amounts_and_names() -> None:
    reference = "ನಿಮ್ಮ ಕಂತು ಐದು ಸಾವಿರ ರೂಪಾಯಿ ಮೂರು ತಿಂಗಳು"
    hypothesis = "ನಿಮ್ಮ ಕಂತು 5000 ರೂಪಾಯಿ ನಾಲ್ಕು ತಿಂಗಳು"  # amount right, 3 -> 4 wrong
    s = score_clip(reference, hypothesis, ["ಕಂತು", "ಮಂಜುನಾಥ"])
    assert s.entity_total == 4  # 5000, 3, and the two names
    assert s.entity_correct == 2  # 5000 and ಕಂತು (ಮಂಜುನಾಥ is not in the reference's text either)
    correct, missed = entity_hits(s.ref_norm, s.hyp_norm, ["ಕಂತು"])
    assert "5000" in correct and "3" in missed


def test_amount_in_words_matches_amount_in_digits() -> None:
    s = score_clip("दो लाख रुपये बाकी है", "200000 रुपये बाकी है")
    assert s.wer == 0.0
    assert (s.entity_total, s.entity_correct) == (1, 1)


def test_empty_reference_scores_without_dividing_by_zero() -> None:
    s = score_clip("", "")
    assert (s.wer, s.cer, s.entity_total) == (0.0, 0.0, 0)
    assert score_clip("", "noise").wer == 1.0
