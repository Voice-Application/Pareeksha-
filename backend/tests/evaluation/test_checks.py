from typing import Any

from pareeksha.evaluation.checks import (
    check_amounts,
    check_disclosures,
    check_forbidden,
    check_language,
    check_no_loop,
    check_tool_calls,
    run_checks,
)
from pareeksha.evaluation.types import Turn


def T(idx, speaker, text, lang=None):
    return Turn(
        idx=idx,
        speaker=speaker,
        start_ms=idx * 1000,
        end_ms=idx * 1000 + 800,
        text=text,
        language_detected=lang,
    )


DISCLOSURES: list[dict[str, Any]] = [
    {"id": "recording", "text": "this call is being recorded", "within_turns": 2},
    {
        "id": "identity",
        "text": "I am an automated assistant",
        "regex": r"automated (assistant|agent)",
    },
]


def test_disclosure_present_within_window():
    turns = [
        T(0, "agent", "Hello! This call is being recorded for quality."),
        T(1, "caller", "ok"),
        T(2, "agent", "I am an automated assistant of ACME."),
    ]
    res = {r.check_key: r for r in check_disclosures(turns, DISCLOSURES)}
    assert res["recording"].passed is True and res["recording"].evidence_turns == (0,)
    assert res["identity"].passed is True and res["identity"].check_type == "disclosure_present"


def test_disclosure_missing_or_too_late_fails_with_evidence():
    turns = [
        T(0, "agent", "Hello"),
        T(1, "caller", "hi"),
        T(2, "agent", "How can I help?"),
        T(3, "agent", "By the way this call is being recorded"),
    ]
    r = check_disclosures(turns, DISCLOSURES[:1])[0]
    assert r.passed is False and r.must_pass is True
    assert r.evidence_turns == (0, 2)  # the agent turns that were inspected
    assert "first 2 agent turns" in r.detail


def test_disclosure_ignores_caller_speech_and_tolerates_stt_noise():
    turns = [T(0, "caller", "this call is being recorded"), T(1, "agent", "welcome")]
    assert check_disclosures(turns, DISCLOSURES[:1])[0].passed is False
    noisy = [T(0, "agent", "this call is been recorded for the quality purposes")]
    assert check_disclosures(noisy, DISCLOSURES[:1])[0].passed is True


def test_forbidden_absent():
    phrases = [
        {"id": "threat", "text": "we will send someone to your house"},
        {"id": "legal", "text": "x", "regex": r"\blegal action\b"},
    ]
    ok = [
        T(0, "agent", "Please pay by Friday."),
        T(1, "caller", "legal action? we will send someone to your house"),
    ]
    assert all(r.passed for r in check_forbidden(ok, phrases))  # caller words never count
    bad = [
        T(0, "agent", "Pay or we will send someone to your house."),
        T(1, "agent", "Legal Action follows."),
    ]
    res = {r.check_key: r for r in check_forbidden(bad, phrases)}
    assert res["threat"].passed is False and res["threat"].evidence_turns == (0,)
    assert res["legal"].passed is False and res["legal"].evidence_turns == (1,)
    assert res["legal"].check_type == "forbidden_absent"


def test_language_match():
    kn = [
        T(0, "agent", "ನಮಸ್ಕಾರ, ನಿಮ್ಮ ಕಂತು ನಾಲ್ಕು ಸಾವಿರ ರೂಪಾಯಿ"),
        T(1, "agent", "ಧನ್ಯವಾದಗಳು ಸರ್"),
    ]
    assert check_language(kn, "kn-IN").passed is True
    en = [
        T(0, "agent", "Hello sir your installment is four thousand rupees"),
        T(1, "agent", "Please pay before the due date sir"),
        T(2, "agent", "ನಮಸ್ಕಾರ ಧನ್ಯವಾದಗಳು ಸರ್"),
    ]
    r = check_language(en, "kn-IN")
    assert r.passed is False and r.evidence_turns == (0, 1) and r.must_pass is False
    assert check_language(en, "kn-IN", allowed=["en-IN"]).passed is True  # caller switches language
    assert check_language([T(0, "agent", "OK sir")], "kn-IN").passed is None
    detected = [
        T(0, "agent", "x y z w", lang="hi-IN"),
        T(1, "agent", "x y z w", lang="hi-IN"),
    ]
    assert check_language(detected, "hi-IN").passed is True
    assert check_language(detected, "kn-IN").passed is False


def test_no_loop():
    msg = "I did not understand, could you please repeat that again"
    looping = [
        T(0, "agent", msg),
        T(1, "caller", "..."),
        T(2, "agent", msg + "?"),
        T(3, "caller", "..."),
        T(4, "agent", msg),
    ]
    r = check_no_loop(looping)
    assert r.passed is False and r.evidence_turns == (0, 2, 4)
    once = looping[:3]
    assert check_no_loop(once).passed is True  # one repeat is friction, not a loop
    assert check_no_loop([T(0, "caller", "hi")]).passed is None


def test_tool_calls_expected():
    expected = [
        {
            "name": "record_ptp",
            "args": {"amount": 4000, "date": "2026-11-05"},
            "order": 2,
        },
        {"name": "verify_customer", "args": {}, "order": 1},
    ]
    actual = [
        {"name": "verify_customer", "args": {"id": "x"}, "turn_idx": 1},
        {
            "name": "record_ptp",
            "args": {"amount": "4,000", "date": "2026-11-05", "extra": 1},
            "turn_idx": 4,
        },
    ]
    res = check_tool_calls(expected, actual)
    assert [r.passed for r in res] == [True, True]
    assert res[0].evidence_turns == (4,)

    wrong_amount = [
        {"name": "verify_customer", "args": {}},
        {"name": "record_ptp", "args": {"amount": 40000, "date": "2026-11-05"}},
    ]
    res = check_tool_calls(expected, wrong_amount)
    assert (
        res[0].passed is False and "different arguments" in res[0].detail and res[1].passed is True
    )

    missing = check_tool_calls(expected, [])
    assert [r.passed for r in missing] == [False, False] and "never called" in missing[0].detail

    wrong_order = check_tool_calls(expected, list(reversed(actual)))
    assert [r.passed for r in wrong_order] == [
        False,
        True,
    ]  # record_ptp came before verify_customer
    assert "before verify_customer" in wrong_order[0].detail

    assert [r.passed for r in check_tool_calls(expected, None)] == [None, None]
    assert check_tool_calls([], [{"name": "x"}]) == []


def test_amount_confirmed_catches_40000_vs_4000():
    turns = [
        T(0, "caller", "I will pay four thousand"),
        T(1, "agent", "Okay, I have noted a payment of Rs 40,000 on Friday."),
    ]
    r = check_amounts(turns, {"emi_amount": 4000})[0]
    assert r.check_type == "amount_confirmed" and r.check_key == "emi_amount"
    assert r.passed is False and r.evidence_turns == (1,)
    assert r.detail == "Expected 4000; agent confirmed 40000"


def test_amount_confirmed_pass_selfcorrect_and_na():
    good = [T(0, "agent", "Your EMI is चार हज़ार रुपये, correct?")]
    assert check_amounts(good, {"emi": 4000})[0].passed is True
    fixed = [
        T(0, "agent", "That is 40000 rupees."),
        T(1, "caller", "no"),
        T(2, "agent", "Sorry, 4000 rupees."),
    ]
    assert check_amounts(fixed, {"emi": 4000})[0].passed is True
    still_wrong = [
        T(0, "agent", "4000 rupees."),
        T(1, "agent", "So 40000 rupees then."),
    ]
    assert check_amounts(still_wrong, {"emi": 4000})[0].passed is False
    assert check_amounts([T(0, "agent", "Hello, how are you?")], {"emi": 4000})[0].passed is None


def test_amount_confirmed_ignores_dates_and_other_known_amounts():
    turns = [T(0, "agent", "Due on 5 November 2026, EMI 4000 plus penalty 250 rupees.")]
    res = check_amounts(turns, {"emi": 4000, "penalty": 250})
    assert [r.passed for r in res] == [True, True]


def test_run_checks_integration():
    turns = [
        T(0, "agent", "Hello, this call is being recorded."),
        T(1, "caller", "I pay 4000"),
        T(2, "agent", "Noted 40000 rupees, or we will send someone to your house."),
    ]
    res = run_checks(
        turns,
        disclosures=DISCLOSURES[:1],
        forbidden=[{"id": "threat", "text": "we will send someone to your house"}],
        expected_language="en-IN",
        expected_tool_calls=[{"name": "record_ptp", "args": {}}],
        tool_calls=[],
        expected_amounts={"emi": 4000},
    )
    got = {(r.check_type, r.check_key): r.passed for r in res}
    assert got == {
        ("disclosure_present", "recording"): True,
        ("forbidden_absent", "threat"): False,
        ("language_match", "en-IN"): True,
        ("no_loop", "agent_repeats"): True,
        ("tool_calls_expected", "record_ptp"): False,
        ("amount_confirmed", "emi"): False,
    }
    assert res[0].to_dict()["check_type"] == "disclosure_present"


def _emi_call(readback: bool):
    turns = [
        T(0, "agent", "Hello, this is Suraksha Finance."),
        T(1, "caller", "Yes speaking."),
        T(
            2,
            "agent",
            "Your EMI of rupees four thousand five hundred is overdue. When can you pay?",
        ),
        T(3, "caller", "I will pay the full amount on Friday."),
    ]
    if readback:
        turns += [
            T(
                4,
                "agent",
                "Just to confirm, you will pay four thousand five hundred rupees on Friday. Is that right?",
            ),
            T(5, "caller", "Yes."),
            T(6, "agent", "Noted, goodbye."),
        ]
    else:
        turns.append(T(4, "agent", "Thank you, I have noted your promise. Goodbye."))
    from pareeksha.evaluation.types import ToolCall

    tool = [
        ToolCall(
            "record_promise_to_pay", {"amount_inr": 4500, "when": "Friday"}, turn_idx=turns[-1].idx
        )
    ]
    return turns, tool


def test_amount_readback_missing_before_acting_fails_and_clean_passes():
    turns, tool = _emi_call(readback=False)
    r = check_amounts(turns, {"emi_amount": 4500}, tool)[0]
    assert r.passed is False and r.must_pass and r.evidence_turns == (2, 4)
    turns, tool = _emi_call(readback=True)
    assert check_amounts(turns, {"emi_amount": 4500}, tool)[0].passed is True
    # no action taken (caller hung up after the first statement): not failed
    turns, _ = _emi_call(readback=False)
    assert check_amounts(turns, {"emi_amount": 4500}, [])[0].passed is True
