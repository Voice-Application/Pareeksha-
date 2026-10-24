from mock_agent.bugs import Bug, bugs_from_env, parse_bugs
from mock_agent.policy import DISCLOSURE, Dialog, Reply, detect_language


def _run(dialog: Dialog, *heard: str) -> list[Reply]:
    return [dialog.respond(h) for h in heard]


def test_happy_path_english() -> None:
    d = Dialog("en-IN")
    opening = d.opening()
    assert DISCLOSURE["en-IN"] in opening.text
    ask, confirm, closing = _run(d, "yes speaking", "I will pay on Friday", "yes correct")
    assert "overdue" in ask.text
    assert "confirm" in confirm.text and "four thousand five hundred" in confirm.text
    assert closing.end_call and closing.tool_calls[0][0] == "record_promise_to_pay"
    assert d.promised


def test_bug_no_disclosure() -> None:
    d = Dialog("en-IN", frozenset({Bug.NO_DISCLOSURE}))
    assert "recorded" not in d.opening().text


def test_bug_no_amount_confirm_skips_confirmation_turn() -> None:
    d = Dialog("en-IN", frozenset({Bug.NO_AMOUNT_CONFIRM}))
    d.opening()
    _, closing = _run(d, "yes", "friday")
    assert closing.end_call and "confirm" not in closing.text


def test_bug_english_to_kannada_only_affects_kannada() -> None:
    kn = Dialog("kn-IN", frozenset({Bug.ENGLISH_TO_KANNADA}))
    assert kn.opening().language == "en-IN"
    assert kn.respond("ಹೌದು").language == "en-IN"
    hi = Dialog("hi-IN", frozenset({Bug.ENGLISH_TO_KANNADA}))
    assert hi.opening().language == "hi-IN"
    assert Dialog("kn-IN").opening().language == "kn-IN"


def test_waiver_refused_with_escalation_when_clean() -> None:
    d = Dialog("en-IN")
    d.opening()
    r = d.respond("can you waive the late fee")
    assert "not able to waive" in r.text
    assert r.tool_calls[0][0] == "escalate_waiver_request"


def test_bug_false_waiver_promises_waiver_without_tool() -> None:
    d = Dialog("en-IN", frozenset({Bug.FALSE_WAIVER}))
    d.opening()
    r = d.respond("please waive the penalty")
    assert "I will waive" in r.text and r.tool_calls == ()


def test_hindi_and_kannada_waiver_keywords() -> None:
    for lang, said in (("hi-IN", "लेट फीस माफ़ कर दीजिए"), ("kn-IN", "ತಡ ಶುಲ್ಕ ಮನ್ನಾ ಮಾಡಿ")):
        d = Dialog(lang)
        d.opening()
        assert d.respond(said).tool_calls[0][0] == "escalate_waiver_request"


def test_language_switches_by_script() -> None:
    assert detect_language("ಹೌದು", "en-IN") == "kn-IN"
    assert detect_language("हाँ", "en-IN") == "hi-IN"
    assert detect_language("yes", "hi-IN") == "hi-IN"


def test_empty_utterances_reprompt_then_hang_up() -> None:
    d = Dialog("en-IN")
    d.opening()
    a, b, c = _run(d, "", " ", "")
    assert not a.end_call and not b.end_call and c.end_call


def test_after_done_closes_again() -> None:
    d = Dialog("en-IN")
    d.opening()
    _run(d, "yes", "friday", "yes")
    assert d.respond("hello").end_call


def test_bug_parsing() -> None:
    assert parse_bugs(None) == frozenset()
    assert parse_bugs("no_disclosure, false_waiver") == {Bug.NO_DISCLOSURE, Bug.FALSE_WAIVER}
    assert parse_bugs(["ignore_interrupt"]) == {Bug.IGNORE_INTERRUPT}
    assert bugs_from_env({"MOCK_BUGS": "no_amount_confirm"}) == {Bug.NO_AMOUNT_CONFIRM}
    assert len(Bug) == 5
