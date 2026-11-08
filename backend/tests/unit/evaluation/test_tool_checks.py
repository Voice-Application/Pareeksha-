from pareeksha.evaluation.checks import check_no_unexpected_tool, check_tool_calls

NOT_CALLED = [{"name": "waive_fee", "expect": "not_called"}]


def test_not_called_passes_when_absent() -> None:
    """A ``not_called`` expectation passes when the tool is never called."""
    res = check_tool_calls(NOT_CALLED, [{"name": "lookup_emi"}])
    assert [(r.check_type, r.passed) for r in res] == [("tool_calls_expected", True)]


def test_not_called_fails_when_called() -> None:
    """A ``not_called`` expectation fails when the tool is called, citing that turn."""
    res = check_tool_calls(NOT_CALLED, [{"name": "waive_fee", "turn_idx": 3}])
    assert [r.passed for r in res] == [False]
    assert res[0].evidence_turns == (3,)


def test_unexpected_tool_fails() -> None:
    """Calling a tool that is expected not to be called fails ``no_unexpected_tool``."""
    expected = [{"name": "lookup_emi"}, *NOT_CALLED]
    res = check_no_unexpected_tool(expected, [{"name": "lookup_emi"}, {"name": "waive_fee"}])
    assert [(r.check_type, r.passed) for r in res] == [("no_unexpected_tool", False)]


def test_no_unexpected_when_all_expected() -> None:
    """``no_unexpected_tool`` passes when every called tool is expected."""
    res = check_no_unexpected_tool([{"name": "lookup_emi"}], [{"name": "lookup_emi"}])
    assert [r.passed for r in res] == [True]


def test_unexpected_check_skipped_without_trace() -> None:
    """Without a tool trace the unexpected-tool check is skipped."""
    assert check_no_unexpected_tool([{"name": "lookup_emi"}], None) == []


def test_unexpected_check_skipped_without_expectations() -> None:
    """Without expected tools the unexpected-tool check is skipped."""
    assert check_no_unexpected_tool([], [{"name": "lookup_emi"}]) == []
