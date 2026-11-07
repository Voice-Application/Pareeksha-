"""ReportedToolCall bounds."""

import pytest
from pydantic import ValidationError

from pareeksha.schemas.calls import ReportedToolCall


def test_small_payload_is_accepted() -> None:
    assert ReportedToolCall(name="x", arguments={"a": "b" * 100}, result={"ok": 1}).at_ms == 0


@pytest.mark.parametrize("field", ["arguments", "result"])
def test_oversized_arguments_or_result_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        ReportedToolCall.model_validate({"name": "x", field: {"blob": "z" * 5000}})
