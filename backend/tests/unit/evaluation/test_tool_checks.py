from pareeksha.evaluation.checks import check_no_unexpected_tool, check_tool_calls

NOT_CALLED = [{"name": "waive_fee", "expect": "not_called"}]


def test_not_called_passes_when_absent() -> None:
    res = check_tool_calls(NOT_CALLED, [{"name": "lookup_emi"}])
    assert [(r.check_type, r.passed) for r in res] == [("tool_calls_expected", True)]


def test_not_called_fails_when_called() -> None:
    res = check_tool_calls(NOT_CALLED, [{"name": "waive_fee", "turn_idx": 3}])
    assert [r.passed for r in res] == [False]
    assert res[0].evidence_turns == (3,)


def test_unexpected_tool_fails() -> None:
    expected = [{"name": "lookup_emi"}, *NOT_CALLED]
    res = check_no_unexpected_tool(expected, [{"name": "lookup_emi"}, {"name": "waive_fee"}])
    assert [(r.check_type, r.passed) for r in res] == [("no_unexpected_tool", False)]


def test_no_unexpected_when_all_expected() -> None:
    res = check_no_unexpected_tool([{"name": "lookup_emi"}], [{"name": "lookup_emi"}])
    assert [r.passed for r in res] == [True]


def test_unexpected_check_skipped_without_trace() -> None:
    assert check_no_unexpected_tool([{"name": "lookup_emi"}], None) == []


def test_unexpected_check_skipped_without_expectations() -> None:
    assert check_no_unexpected_tool([], [{"name": "lookup_emi"}]) == []
