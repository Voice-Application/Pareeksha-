from pareeksha.evaluation.checks import check_no_unexpected_tool


def test_unexpected_check_skipped_when_only_not_called_expectations() -> None:
    """A lone 'must not call X' forbids only X; any other tool is not unexpected."""
    expected = [{"name": "waive_fee", "expect": "not_called"}]
    assert check_no_unexpected_tool(expected, [{"name": "lookup_emi"}]) == []
