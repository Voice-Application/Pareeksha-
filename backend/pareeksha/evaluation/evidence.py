"""Evidence validation: every cited turn index must exist in the call (docs/08 principle 3)."""

from __future__ import annotations

from collections.abc import Collection

from pareeksha.schemas.evaluation import JudgeOutput

#: A dimension scored at or below this must cite at least one turn.
MUST_CITE_AT_OR_BELOW = 1


def evidence_problems(output: JudgeOutput, valid_indices: Collection[int]) -> str | None:
    """Return a message for the repair retry, or ``None`` when the evidence is sound."""
    valid = set(valid_indices)
    problems: list[str] = []
    for key, dim in output.dimensions:
        bad = sorted({i for i in dim.evidence_turns if i not in valid})
        if bad:
            problems.append(
                f"{key}.evidence_turns has indices {bad} that are not in the transcript"
            )
        if dim.score <= MUST_CITE_AT_OR_BELOW and not dim.evidence_turns:
            problems.append(f"{key} scored {dim.score} but cites no evidence_turns")
    if not problems:
        return None
    shown = f"{min(valid)}..{max(valid)}" if valid else "none"
    return "; ".join(problems) + f". Valid turn indices are {shown}."
