"""Evidence validation: every cited turn index must exist in the call (docs/08 principle 3)."""

from __future__ import annotations

from collections.abc import Collection

from pareeksha.schemas.evaluation import JudgeOutput

#: A dimension scored at or below this must cite at least one turn.
MUST_CITE_AT_OR_BELOW = 1


def evidence_problems(
    output: JudgeOutput,
    valid_indices: Collection[int],
    agent_indices: Collection[int] = (),
) -> str | None:
    """Return a message for the repair retry, or ``None`` when the evidence is sound.

    The message tells the model exactly how to fix each dimension: cite the turn where the
    problem happens, or for something the agent *failed* to do the turn where it should have
    happened (``agent_indices`` lists the agent's turns to choose from). It must not silently
    raise the score: the score stays what the transcript supports.
    """
    valid = set(valid_indices)
    problems: list[str] = []
    missing_cite = False
    for key, dim in output.dimensions:
        bad = sorted({i for i in dim.evidence_turns if i not in valid})
        if bad:
            problems.append(
                f"{key}.evidence_turns has indices {bad} that are not in the transcript"
            )
        if dim.score <= MUST_CITE_AT_OR_BELOW and not dim.evidence_turns:
            problems.append(f"{key} scored {dim.score} but cites no evidence_turns")
            missing_cite = True
    if not problems:
        return None
    shown = f"{min(valid)}..{max(valid)}" if valid else "none"
    msg = "; ".join(problems) + f". Valid turn indices are {shown}."
    if missing_cite:
        agent = sorted(set(agent_indices) & valid)
        msg += (
            " Every dimension scored 0 or 1 MUST have a non-empty evidence_turns list: cite the turn"
            " where the problem happens, or, for something the agent failed to do, the agent turn"
            " where it should have happened"
            + (f" (agent turns: {agent})" if agent else "")
            + ". Keep the score the transcript supports; do not raise it just to avoid citing."
        )
    return msg
