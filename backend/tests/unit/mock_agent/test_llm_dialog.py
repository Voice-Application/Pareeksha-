"""EVAL-07: the LLM-driven mock agent dialog (fake completer; no network)."""

from __future__ import annotations

import json

from mock_agent.bugs import Bug
from mock_agent.llm_dialog import LLMDialog, grounding_problems, make_dialog
from mock_agent.policy import DISCLOSURE, WAIVER_PROMISE, Dialog


class Fake:
    """Returns the queued replies in order and records the prompts it was given."""

    def __init__(self, *replies: dict | str) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    def __call__(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)


def say(reply: str, action: str = "none", date: str = "") -> dict:
    return {"reply": reply, "action": action, "promise_date": date}


def dialog(
    *replies: dict | str, lang: str = "en-IN", bugs: frozenset[Bug] = frozenset()
) -> tuple[LLMDialog, Fake]:
    fake = Fake(*replies)
    d = LLMDialog(language=lang, bugs=bugs, complete=fake)
    d.opening()
    return d, fake


def test_make_dialog_falls_back_to_scripted_without_a_completer() -> None:
    assert type(make_dialog("en-IN", frozenset(), None)) is Dialog
    assert isinstance(make_dialog("en-IN", frozenset(), Fake()), LLMDialog)


def test_answers_what_the_caller_said_and_keeps_history() -> None:
    d, fake = dialog(
        say("Thank you for letting me know. Could you share the UTR so it can be verified?")
    )
    r = d.respond("I already paid this EMI three days ago by UPI")
    assert "UTR" in r.text and not r.end_call and r.tool_calls == ()
    msgs = fake.calls[0]
    assert msgs[0]["role"] == "system" and "Facts on file" in msgs[0]["content"]
    assert "4500" in msgs[0]["content"] and "already paid" in msgs[0]["content"]
    assert DISCLOSURE["en-IN"] in msgs[1]["content"]
    assert msgs[1]["content"].index(DISCLOSURE["en-IN"]) < msgs[1]["content"].index(
        "Caller: I already paid this EMI three days ago by UPI"
    )


def test_promise_is_recorded_with_the_callers_date() -> None:
    d, _ = dialog(
        say("Just to confirm, you will pay 4,500 rupees on Friday?"),
        say(
            "Thank you, I have recorded your promise for Friday. Goodbye.",
            "record_promise_to_pay",
            "Friday",
        ),
    )
    assert d.respond("I can pay on Friday").tool_calls == ()
    r = d.respond("Yes, correct")
    assert r.end_call and r.tool_calls[0][0] == "record_promise_to_pay"
    assert r.tool_calls[0][1] == {"amount_inr": 4500, "when": "Friday"}


def test_transfer_action() -> None:
    d, _ = dialog(say("Of course, connecting you to a human agent now.", "transfer_to_human"))
    r = d.respond("I want to talk to a human")
    assert r.end_call and r.tool_calls[0][0] == "transfer_to_human"


def test_invented_number_is_retried_then_falls_back_to_scripted() -> None:
    bad = say("Your EMI is overdue by 12 days and the late fee is 500 rupees.")
    d, fake = dialog(bad, bad)
    r = d.respond("How much is the late fee?")
    assert len(fake.calls) == 2 and "cannot be used" in fake.calls[1][-1]["content"]
    assert d.fallbacks == 1 and r.text  # the scripted dialog answered instead
    assert "500 rupees" not in r.text


def test_retry_succeeds() -> None:
    d, _ = dialog(
        say("It is overdue by 12 days."),
        say("I do not have that information; a human agent can tell you."),
    )
    assert "do not have" in d.respond("How many days overdue is it?").text
    assert d.fallbacks == 0


def test_numbers_the_caller_said_may_be_repeated() -> None:
    assert (
        grounding_problems("Noted, UTR 5550100.", "en-IN", ["my UTR is 5550100"], frozenset()) == []
    )
    assert (
        grounding_problems("Your EMI is 4,500 rupees due on the 5th.", "en-IN", [], frozenset())
        == []
    )
    assert grounding_problems("It is 4000.", "en-IN", [], frozenset())


def test_reply_in_the_wrong_script_is_rejected() -> None:
    assert grounding_problems("Thank you", "kn-IN", [], frozenset())
    assert grounding_problems("ಧನ್ಯವಾದ", "kn-IN", [], frozenset()) == []
    assert grounding_problems("धन्यवाद", "en-IN", [], frozenset())


def test_provider_error_falls_back() -> None:
    d, _ = dialog(RuntimeError("timeout"))
    r = d.respond("hello who is this")
    assert d.fallbacks == 1 and r.text


def test_bug_false_waiver_overrides_the_llm() -> None:
    d, fake = dialog(bugs=frozenset({Bug.FALSE_WAIVER}))
    r = d.respond("please waive the late fee")
    assert r.text == WAIVER_PROMISE["en-IN"] and fake.calls == []


def test_bug_english_to_kannada_forces_english() -> None:
    d, fake = dialog(
        say("Thank you. When can you pay?"), lang="kn-IN", bugs=frozenset({Bug.ENGLISH_TO_KANNADA})
    )
    r = d.respond("ಹೌದು, ನಾನೇ ಮಾತಾಡ್ತಿದ್ದೀನಿ")
    assert r.language == "en-IN" and "Reply in English only" in fake.calls[0][0]["content"]


def test_bug_no_disclosure_opening() -> None:
    d, _ = dialog(bugs=frozenset({Bug.NO_DISCLOSURE}))
    assert DISCLOSURE["en-IN"] not in d.turns[0][1]


def test_bug_no_amount_confirm_never_states_the_amount() -> None:
    d, fake = dialog(
        say("Okay, 4,500 rupees on Friday, right?"),  # rejected: states the amount
        say("Thank you, recorded for Friday. Goodbye.", "record_promise_to_pay", "Friday"),
        bugs=frozenset({Bug.NO_AMOUNT_CONFIRM}),
    )
    r = d.respond("I will pay on Friday")
    assert "Never mention the amount" in fake.calls[0][0]["content"]
    assert r.tool_calls[0][0] == "record_promise_to_pay" and "4,500" not in r.text


def test_caller_number_regrouped_is_allowed() -> None:
    assert grounding_problems("Noted, 5550100, thank you.", "en-IN", ["UTR-555-0100"], frozenset()) == []
    assert grounding_problems("Noted 555 0100.", "en-IN", ["UTR-555-0100"], frozenset()) == []
    assert grounding_problems("Noted 555 0199.", "en-IN", ["UTR-555-0100"], frozenset())


def test_transcript_sent_as_one_user_message() -> None:
    d, fake = dialog(say("Yes, I can hear you."))
    d.respond("hello?")
    msgs = fake.calls[0]
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "Agent (you):" in msgs[1]["content"] and "Caller: hello?" in msgs[1]["content"]
