import pytest

from pareeksha.evaluation.pii import mask_pii, mask_pii_detailed


@pytest.mark.parametrize(
    "text,expected",
    [
        ("call me on 9876543210 now", "call me on [PHONE] now"),
        ("my number is +91 98765 43210.", "my number is [PHONE]."),
        ("91-9876543210", "[PHONE]"),
        ("09876543210", "[PHONE]"),
        ("98765-43210 please", "[PHONE] please"),
        ("aadhaar 2345 6789 0123 hai", "aadhaar [AADHAAR] hai"),
        ("aadhaar 234567890123", "aadhaar [AADHAAR]"),
        ("PAN is ABCDE1234F ok", "PAN is [PAN] ok"),
        ("pan abcde1234f", "pan [PAN]"),
        ("mail a.b+c@example.co.in today", "mail [EMAIL] today"),
        ("card 4111 1111 1111 1111 expiry", "card [CARD] expiry"),
        ("card 4111-1111-1111-1111", "card [CARD]"),
        ("फोन ९८७६५४३२१०", "फोन [PHONE]"),
        ("ಫೋನ್ ೯೮೭೬೫೪೩೨೧೦", "ಫೋನ್ [PHONE]"),
        ("nine eight seven six five four three two one zero", "[DIGITS]"),
        ("my number is 9 8 7 6 5 4 3 2 1 0 thanks", "my number is [DIGITS] thanks"),
    ],
)
def test_masks(text, expected):
    assert mask_pii(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "EMI of Rs 4000 is due on 5 November",
        "Loan amount 1234567890",  # 10 digits but not a mobile (starts with 1)
        "reference 12345",
        "amount ₹1,00,000 only",
        "ಕಂತು ೪೦೦೦ ರೂಪಾಯಿ",
        "hello world",
        "",
    ],
)
def test_not_masked(text):
    assert mask_pii(text) == text


def test_non_luhn_16_digits_not_a_card():
    assert "[CARD]" not in mask_pii("ref 4111 1111 1111 1112")


def test_multiple_and_counts():
    r = mask_pii_detailed("a@b.com 9876543210 ABCDE1234F 2345 6789 0123")
    assert r.text == "[EMAIL] [PHONE] [PAN] [AADHAAR]"
    assert r.counts == {"email": 1, "phone": 1, "pan": 1, "aadhaar": 1}
    assert [f.kind for f in r.findings] == ["email", "phone", "pan", "aadhaar"]


def test_masked_text_contains_no_original_digits():
    out = mask_pii("phone 9876543210 aadhaar 234567890123")
    assert not any(c.isdigit() for c in out)


def test_idempotent():
    once = mask_pii("9876543210 and x@y.com")
    assert mask_pii(once) == once
