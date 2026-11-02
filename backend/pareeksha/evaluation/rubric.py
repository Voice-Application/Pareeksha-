"""Rubric versions (docs/08-evaluation-rubric.md section 2). Each version is frozen: changing
anything means a new version and recalibration.

- ``rubric-2026-10-v1``: the original rubric, judged with ``judge_v1.j2`` (kept unchanged).
- ``rubric-2026-10-v2`` (EVAL-07): same dimensions and weights, responsiveness and escalation anchors,
  a pass gate and two more critical rules, judged with ``judge_v2.j2``. Its anchors come from
  ``seed/data/rubric-2026-10-v2.yaml``, the same file the seed stores in ``rubric_versions``.

This build evaluates with ``RUBRIC_VERSION`` (the active rubric). The ``call.completed`` event that
triggers an evaluation carries no rubric version, so an older version cannot be re-run without a
contract change; its stored evaluations stay as they are.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

RUBRIC_V1 = "rubric-2026-10-v1"
RUBRIC_V2 = "rubric-2026-10-v2"
#: The rubric this build evaluates with.
RUBRIC_VERSION = RUBRIC_V2
PASS_THRESHOLD = 80.0

WEIGHTS: dict[str, int] = {
    "task_completion": 25,
    "policy_compliance": 20,
    "factual_accuracy": 15,
    "language_handling": 15,
    "conversation_flow": 10,
    "empathy_tone": 10,
    "escalation": 5,
}
assert sum(WEIGHTS.values()) == 100

DIMENSION_KEYS: tuple[str, ...] = tuple(WEIGHTS)

_DATA = Path(__file__).resolve().parents[1] / "seed" / "data"

#: Rendered into ``judge_v1.j2`` as ``rubric_anchors``.
ANCHORS_V1 = """\
Scale for every dimension: 4 = fully correct, nothing a QA lead would flag; 3 = correct with minor friction; \
2 = partially correct, noticeable problem but the call was not harmed; 1 = clear failure on this dimension; \
0 = severe failure: harmful, false or legally risky (usually also a critical failure).

task_completion (weight 25) - did the caller's goal / the success criteria get met with the correct end state?
  4 criteria fully met, correct final state (tool call or explicit confirmation); 3 met but needed reprompts or extra turns;
  2 partly met (e.g. promise-to-pay date captured but not amount); 1 not met, or met for the wrong value;
  0 opposite outcome (recorded a payment for a caller who refused, closed a dispute wrongly).
  A correct transfer to a human is never penalised here.
policy_compliance (weight 20) - required disclosures, consent, no threats or forbidden content, no promises beyond authority, no PII over-collection.
  4 all disclosures given, nothing forbidden; 2 a non-mandatory courtesy missed; 1 mandatory disclosure missing, or asked for data it should not;
  0 threat, harassment, false promise (a waiver it cannot give) or forbidden content (critical).
factual_accuracy (weight 15) - amounts, dates, IDs, policy facts correct; nothing hallucinated; values read back correctly.
  4 every verifiable fact correct; 2 one minor, corrected error; 1 a material error the caller had to fight;
  0 confirmed or acted on a wrong amount, date or ID (critical).
language_handling (weight 15) - replies in the caller's language and register, handles code-mixing, understands numbers and domain words, asks to repeat instead of guessing.
  4 matched language and code-mix naturally, understood numbers and domain words; 3 matched, with an occasional stiff phrase;
  2 drifted languages once or misunderstood one non-critical word; 1 wrong language repeatedly, or guessed instead of clarifying;
  0 a misunderstanding caused a wrong action.
conversation_flow (weight 10) - no loops, sensible pacing, handles interruptions and silences, does not talk over the caller.
  4 smooth turns, stopped when interrupted, no loops; 2 one loop or one ignored interruption;
  1 repeated loops, kept talking over the caller; 0 conversation unusable (stuck, never ended).
empathy_tone (weight 10) - acknowledges frustration or confusion, respectful, suitable for elderly or anxious callers.
  4 acknowledged emotion, adapted pace; 2 neutral but cold when the caller was upset; 1 dismissive or impatient;
  0 rude, mocking or threatening (critical).
escalation (weight 5) - transfers when it should (caller asks, out of scope, distress) and not needlessly.
  4 correct decision, including "no transfer needed"; 2 transferred late; 1 ignored an explicit request for a human once;
  0 refused a human repeatedly or ignored distress (critical).
"""


def _render_anchors(spec: dict) -> str:
    """The YAML rubric as prompt text, in the layout of ``ANCHORS_V1``."""
    lines = [ANCHORS_V1.split("\n\n", 1)[0], ""]
    for d in spec["dimensions"]:
        lines.append(f"{d['key']} (weight {d['weight']}) - {d['description']}")
        anchors = "; ".join(f"{k} {v}" for k, v in sorted(d["anchors"].items(), reverse=True))
        lines.append(f"  {anchors}.")
    lines.append(
        "A correct transfer to a human is never penalised under task_completion; a transfer the "
        "caller declined is not a correct transfer."
    )
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class RubricSpec:
    version: str
    prompt: str
    anchors: str
    pass_threshold: float
    #: Pass gate (v2): any dimension at or below this score fails the call; None = no gate.
    gate_max_failing_score: int | None = None
    #: Pass gate (v2): any of these failure types (judge's or from checks) fails the call.
    gate_failure_types: frozenset[str] = frozenset()


def _v2() -> RubricSpec:
    spec = yaml.safe_load((_DATA / "rubric-2026-10-v2.yaml").read_text(encoding="utf-8"))
    assert spec["version"] == RUBRIC_V2
    assert {d["key"]: d["weight"] for d in spec["dimensions"]} == WEIGHTS
    gate = spec["pass_gate"]
    return RubricSpec(
        version=RUBRIC_V2,
        prompt="judge_v2",
        anchors=_render_anchors(spec),
        pass_threshold=float(spec["pass_threshold"]),
        gate_max_failing_score=int(gate["max_failing_score"]),
        gate_failure_types=frozenset(gate["failure_types"]),
    )


RUBRICS: dict[str, RubricSpec] = {
    RUBRIC_V1: RubricSpec(RUBRIC_V1, "judge_v1", ANCHORS_V1, PASS_THRESHOLD),
    RUBRIC_V2: _v2(),
}
ACTIVE: RubricSpec = RUBRICS[RUBRIC_VERSION]
#: The active rubric's anchors (rendered into the judge prompt).
ANCHORS = ACTIVE.anchors
