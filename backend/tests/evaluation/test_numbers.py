import pytest

from pareeksha.evaluation.numbers import (
    extract_amounts,
    extract_numbers,
    normalize_numbers,
    parse_number,
    to_ascii_digits,
)


@pytest.mark.parametrize(
    "text,value",
    [
        ("4000", 4000),
        ("4,000", 4000),
        ("1,00,000", 100000),
        ("₹4,000", 4000),
        ("Rs.1,00,000/-", 100000),
        ("Rs 25,000", 25000),
        ("4000.00", 4000),
        ("4k", 4000),
        ("2.5 lakh", 250000),
        ("10 crore", 100000000),
        ("1.5 lakh", 150000),
        ("४०००", 4000),
        ("೪೦೦೦", 4000),
        ("१,००,०००", 100000),
        # English words
        ("forty", 40),
        ("twenty-five", 25),
        ("four thousand", 4000),
        ("four thousand five hundred rupees", 4500),
        ("one hundred and five", 105),
        ("one lakh twenty five thousand", 125000),
        ("two crore", 20000000),
        ("twenty five hundred", 2500),
        ("hundred", 100),
        ("three lakh fifty thousand", 350000),
        # Hindi
        ("चार हज़ार", 4000),
        ("चार हजार", 4000),
        ("पच्चीस हज़ार रुपये", 25000),
        ("तीन सौ पचास", 350),
        ("एक लाख बीस हज़ार", 120000),
        ("डेढ़ लाख", 150000),
        ("ढाई हज़ार", 2500),
        ("सवा लाख", 125000),
        ("साढ़े तीन हज़ार", 3500),
        ("निन्यानवे", 99),
        ("पाँच सौ", 500),
        ("पांच सौ", 500),
        ("दो करोड़", 20000000),
        # Kannada
        ("ನಾಲ್ಕು ಸಾವಿರ", 4000),
        ("ಇಪ್ಪತ್ತೈದು", 25),
        ("ಇಪ್ಪತ್ತೊಂದು", 21),
        ("ಮೂವತ್ತು", 30),
        ("ಐನೂರು", 500),
        ("ನಾಲ್ಕು ಸಾವಿರದ ಐನೂರು", 4500),
        ("ಎರಡು ಲಕ್ಷ", 200000),
        ("ಹದಿನೈದು ಸಾವಿರ", 15000),
        ("ಎಂಬತ್ತೆರಡು", 82),
        # Romanised
        ("naalku saavira", 4000),
        ("char hazaar", 4000),
        ("ondu laksha", 100000),
        ("paanch sau", 500),
    ],
)
def test_parse_number(text, value):
    assert parse_number(text) == value


def test_four_thousand_in_every_form_agrees():
    forms = [
        "4000",
        "4,000",
        "four thousand",
        "चार हज़ार",
        "ನಾಲ್ಕು ಸಾವಿರ",
        "naalku saavira",
    ]
    assert {parse_number(f) for f in forms} == {4000}


def test_extract_in_sentence_with_spans():
    text = "Your EMI is four thousand five hundred rupees, due on 5 and penalty Rs.250."
    nums = extract_numbers(text)
    assert [n.value for n in nums] == [4500, 5, 250]
    assert text[nums[0].start : nums[0].end] == "four thousand five hundred"
    assert [n.currency for n in nums] == [True, False, True]
    assert [n.value for n in extract_amounts(text)] == [4500, 250]


def test_adjacent_numbers_are_separate():
    assert [n.value for n in extract_numbers("nine eight seven")] == [9, 8, 7]
    assert [n.value for n in extract_numbers("4000 500")] == [4000, 500]
    assert [n.value for n in extract_numbers("twenty five thirty")] == [25, 30]


def test_lone_one_and_do_are_not_numbers():
    assert extract_numbers("I want one thing") == []
    assert extract_numbers("kya do saal baad") == []
    assert parse_number("one") is None
    assert [n.value for n in extract_numbers("one rupee")] == [1]


def test_non_numbers_return_none():
    assert parse_number("hello there") is None
    assert parse_number("4000 and 500") is None
    assert parse_number("pay 4000 tomorrow") is None
    assert parse_number("") is None


def test_normalize_numbers():
    assert normalize_numbers("EMI ₹4,000 due") == "EMI ₹4000 due"
    assert normalize_numbers("चार हज़ार रुपये") == "4000 रुपये"
    assert normalize_numbers("ನಾಲ್ಕು ಸಾವಿರ ರೂಪಾಯಿ") == "4000 ರೂಪಾಯಿ"
    assert normalize_numbers("account 007") == "account 007"  # plain digit strings untouched
    assert normalize_numbers("one lakh twenty five thousand and two") == "125002"
    assert normalize_numbers("no digits here") == "no digits here"


def test_hindi_two_digit_table_is_complete_and_correct():
    from pareeksha.evaluation import numbers as nb

    hindi_words = [
        w for w, (k, v) in nb._LEX.items() if "ऀ" <= w[0] <= "ॿ" and k in ("unit", "teen", "two")
    ]
    values = sorted({int(nb._LEX[w][1]) for w in hindi_words})
    assert values == list(range(100))
    assert parse_number("उनहत्तर") == 69 and parse_number("अट्ठासी") == 88
    assert parse_number("इक्यावन") == 51 and parse_number("छियानवे") == 96


def test_digit_conversion_is_length_preserving():
    s = "४०००ab೪೦"
    assert to_ascii_digits(s) == "4000ab40" and len(to_ascii_digits(s)) == len(s)
