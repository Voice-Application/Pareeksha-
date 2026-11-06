"""EVAL-08: rubric-2026-11-v3, one test group per owner rule (R-a to R-e), the judge_v3 prompt."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from pareeksha.evaluation import rubric
from pareeksha.evaluation.checks import check_disclosures, english_spelled, stt_spellings
from pareeksha.evaluation.evaluator import merge_failure_types
from pareeksha.evaluation.judge import JUDGE_PROMPT, JudgeInput, render_judge_prompt
from pareeksha.evaluation.metrics import compute_metrics
from pareeksha.evaluation.scoring import finalize_scores
from pareeksha.evaluation.types import CheckResult
from pareeksha.llm.prompts import prompt_hash
from pareeksha.schemas.evaluation import JudgeOutput
from pareeksha.seed.runner import RUBRIC_FILES
from tests.fixtures import synthetic_calls as sc
from tests.unit.evaluation.fakes import judge_json

V2, V3 = rubric.RUBRICS[rubric.RUBRIC_V2], rubric.RUBRICS[rubric.RUBRIC_V3]
KEYS = rubric.DIMENSION_KEYS
SEED = rubric._DATA / "agent_emi.yaml"


def judged(scores: tuple[int, ...] = (4,) * 7, **kw: object) -> JudgeOutput:
    return JudgeOutput.model_validate_json(judge_json(scores, **kw))  # type: ignore[arg-type]


def verdict(
    judge: JudgeOutput, checks: list[CheckResult] | None = None
) -> tuple[bool, bool, list[str]]:
    checks = checks or []
    out = finalize_scores(
        judge, checks, merge_failure_types(judge.failure_types, checks), rubric=V3
    )
    return out.passed, out.critical_failure, out.review_reasons


def turns(*agent_lines: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for i, line in enumerate(agent_lines):
        out.append({"idx": 2 * i, "speaker": "agent", "text": line, "start_ms": 0, "end_ms": 1})
        out.append(
            {"idx": 2 * i + 1, "speaker": "caller", "text": "ok", "start_ms": 0, "end_ms": 1}
        )
    return out


def seeded_disclosures() -> list[dict[str, object]]:
    spec = yaml.safe_load(SEED.read_text(encoding="utf-8"))
    return list(spec["mandatory_disclosures"])


# -- the version itself ----------------------------------------------------------------------


def test_v3_is_active_and_older_versions_are_kept() -> None:
    assert rubric.RUBRIC_VERSION == rubric.RUBRIC_V3 == rubric.ACTIVE.version
    assert JUDGE_PROMPT == "judge_v3" and V3.prompt == "judge_v3"
    assert V2.prompt == "judge_v2" and V2.gate_failure_types == {"intent_miss", "loop"}
    assert rubric.RUBRICS[rubric.RUBRIC_V1].prompt == "judge_v1"
    assert len({prompt_hash("judge_v1"), prompt_hash("judge_v2"), prompt_hash("judge_v3")}) == 3
    assert RUBRIC_FILES[-1] == "rubric-2026-11-v3.yaml"


def test_v3_yaml_parsed() -> None:
    spec = yaml.safe_load((rubric._DATA / "rubric-2026-11-v3.yaml").read_text(encoding="utf-8"))
    assert {d["key"]: d["weight"] for d in spec["dimensions"]} == rubric.WEIGHTS
    assert V3.pass_threshold == 80.0
    assert V3.gate_max_failing_score is None
    assert V3.gate_failure_types == {"missing_disclosure", "intent_miss"}
    assert V3.advisory_checks == {"amount_confirmed"}
    for d in spec["dimensions"]:
        for text in d["anchors"].values():
            assert text in V3.anchors


def test_clean_call_passes() -> None:
    assert verdict(judged()) == (True, False, [])


def test_no_per_dimension_gate() -> None:
    passed, _, reasons = verdict(judged((4, 4, 4, 4, 1, 4, 4)))  # 92.5, flow 1
    assert passed and reasons == []


def test_below_threshold_still_fails() -> None:
    assert not verdict(judged((2, 4, 4, 1, 4, 4, 4)))[0]  # 76.25


# -- R-a disclosure: recording AND company identity, else fail -------------------------------


def test_ra_judge_missing_disclosure_fails_even_at_score_100() -> None:
    passed, critical, reasons = verdict(judged(failure_types=["missing_disclosure"]))
    assert not passed and not critical and reasons == ["gate:missing_disclosure"]


@pytest.mark.parametrize("which", ["recording", "company"])
def test_ra_failed_disclosure_check_fails(which: str) -> None:
    check = CheckResult("disclosure_present", which, passed=False, must_pass=True)
    passed, _, reasons = verdict(judged(), [check])
    assert not passed
    assert "check_failed:disclosure_present" in reasons and "gate:missing_disclosure" in reasons


def test_ra_seed_agent_requires_recording_and_company() -> None:
    ds = seeded_disclosures()
    assert {d["id"] for d in ds} == {"recording", "company"}
    full = turns(
        "Hello, this is Suraksha Finance. This call is being recorded.", "When can you pay?"
    )
    assert all(r.passed for r in check_disclosures(full, ds))
    no_company = turns("Hello. This call is being recorded.", "When can you pay?")
    assert [r.check_key for r in check_disclosures(no_company, ds) if not r.passed] == ["company"]
    no_record = turns("Hello, this is Suraksha Finance.", "When can you pay?")
    assert [r.check_key for r in check_disclosures(no_record, ds) if not r.passed] == ["recording"]


def test_ra_company_counts_anywhere_in_the_call() -> None:
    """R-a says "never says": a company name in the agent's third turn (EVAL-06 L28) counts."""
    ds = seeded_disclosures()
    late = turns("This call is being recorded.", "Hello?", "Namaskara, this is Suraksha Finance.")
    assert all(r.passed for r in check_disclosures(late, ds))
    rec = next(d for d in ds if d["id"] == "recording")
    assert rec["within_turns"] == 2  # the recording disclosure keeps its first-two-turns rule


# -- ISSUE-4: STT spellings of English words ---------------------------------------------------

# Agent turns as Kannada STT wrote an English disclosure (EVAL-07 H12, H17, H27/H28 forms).
KN_STT = [
    "ಹಲೋ ದಿಸ್ ಈಸ್ ಸುರಕ್ಷಾ ಫೈನಾನ್ಸ್ ದಿಸ್ ಕಾಲ್ ಈಸ್ ಬೀಯಿಂಗ್ ರೆಕಾರ್ಡೆಡ್ ಫಾರ್ ಕ್ವಾಲಿಟಿ",
    "ದಿಸ್ ಕಾಲ್ ಈಸ್ ಬೀಯಿಂಗ್ ರೆಕಾರ್ಡರ್ ಫಾರ್ ಕ್ವಾಲಿಟಿ ಸುರಕ್ಷಾ ಫೈನಾನ್ಸ್",
    "ದಿಸ್ ಕಾಲ್ ಈಸ್ ಬೀಯಿಂಗ್ ರೆಕಾರ್ಡರ್ಡ್ ಸುರಕ್ಷಾ ಫೈನಾನ್ಸ್",
]


@pytest.mark.parametrize("text", KN_STT)
def test_issue4_kannada_stt_spellings_pass_the_seeded_regex(text: str) -> None:
    ds = seeded_disclosures()
    assert all(r.passed for r in check_disclosures(turns(text), ds))


def test_issue4_hindi_and_english_still_match() -> None:
    ds = seeded_disclosures()
    for text in (
        "नमस्ते, मैं सुरक्षा फाइनेंस से बोल रही हूँ। यह कॉल रिकॉर्डिंग की जा रही है।",
        "Hello, this is Suraksha Finance. This call is being recorded.",
    ):
        assert all(r.passed for r in check_disclosures(turns(text), ds))


def test_issue4_mapping_is_grounded_not_fuzzy() -> None:
    ds = seeded_disclosures()
    # A Kannada sentence with no disclosure, and near-miss spellings not seen in any transcript.
    for text in ("ಸುರಕ್ಷಾ ಫೈನಾನ್ಸ್ ನಿಮ್ಮ ಇಎಂಐ ಬಾಕಿ ಇದೆ", "ಸುರಕ್ಷಾ ರಿಕಾರ್ಡಿಂಗ್ ರಕಾರ್ಡ"):
        rec = [r for r in check_disclosures(turns(text), ds) if r.check_key == "recording"]
        assert rec[0].passed is False
    assert english_spelled("ಬೀಯಿಂಗ್ ರೆಕಾರ್ಡೆಡ್") == "ಬೀಯಿಂಗ್  recorded "
    assert english_spelled("ಈ ಕರೆ") == "ಈ ಕರೆ"
    spellings = [s for s, _ in stt_spellings()]
    assert len(spellings) == len(set(spellings)) == 8
    # Longest first, so "ರೆಕಾರ್ಡೆಡ್" is not cut down to "record" + "ೆಡ್".
    assert spellings.index("ರೆಕಾರ್ಡೆಡ್") < spellings.index("ರೆಕಾರ್ಡ್")


# -- R-b repetition costs a point, never fails alone -------------------------------------------


def test_rb_loop_alone_does_not_fail() -> None:
    passed, critical, reasons = verdict(judged((4, 4, 4, 4, 3, 4, 4), failure_types=["loop"]))
    assert passed and not critical and reasons == []


def test_rb_failed_no_loop_check_does_not_fail() -> None:
    check = CheckResult("no_loop", "agent_repeats", passed=False, must_pass=False)
    assert verdict(judged((4, 4, 4, 4, 3, 4, 4)), [check])[0]


def test_rb_anchor_is_one_point() -> None:
    flow = next(d for d in _spec()["dimensions"] if d["key"] == "conversation_flow")
    assert "repeated the same sentence" in flow["anchors"][3]
    empathy = next(d for d in _spec()["dimensions"] if d["key"] == "empathy_tone")
    assert not any("repeat" in a for a in empathy["anchors"].values())


# -- R-c amount read-back is not must-pass ----------------------------------------------------


def test_rc_failed_amount_confirmed_does_not_block() -> None:
    check = CheckResult("amount_confirmed", "emi_amount", passed=False, must_pass=True)
    passed, _, reasons = verdict(judged(), [check])
    assert passed and reasons == []
    # v2 still treats it as must-pass (unchanged).
    assert not finalize_scores(judged(), [check], rubric=V2).passed


# -- R-d missed points fail --------------------------------------------------------------------


def test_rd_missed_point_fails() -> None:
    passed, critical, reasons = verdict(
        judged((1, 4, 4, 4, 4, 4, 4), failure_types=["intent_miss"])
    )
    assert not passed and not critical and reasons == ["gate:intent_miss"]


# -- R-e confirmation is not fabrication ------------------------------------------------------


def test_re_fabricated_commitment_is_critical() -> None:
    passed, critical, reasons = verdict(
        judged((4, 4, 0, 4, 4, 4, 4), critical=True, failure_types=["wrong_fact"])
    )
    assert not passed and critical and reasons[0] == "critical_failure"


def test_judge_v3_prompt_states_the_owner_rules() -> None:
    snap = sc.clean_call()
    ts = list(snap.turns)
    text = render_judge_prompt(
        JudgeInput(
            agent=snap.agent,
            turns=ts,
            metrics=compute_metrics(ts, 0),
            checks=[],
            scenario=snap.scenario,
            persona=snap.persona,
        )
    )
    assert "## Owner rules" in text
    assert "which company is calling" in text  # R-a
    assert "costs exactly one point on conversation_flow" in text  # R-b
    assert "only when the caller asks" in text  # R-c
    assert "add intent_miss" in text  # R-d
    assert "Confirmation is not fabrication" in text  # R-e
    assert "asserted or recorded a commitment or fact the caller never gave or confirmed" in text
    assert "stopped responding: the caller spoke" not in text  # v2-only critical rule dropped
    assert "repeated the same sentence or script line" in text  # v3 anchors rendered


def _spec() -> dict[str, Any]:
    text = (rubric._DATA / "rubric-2026-11-v3.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)  # type: ignore[no-any-return]
