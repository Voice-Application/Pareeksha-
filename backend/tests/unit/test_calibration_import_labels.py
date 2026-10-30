"""EVAL-06: validation and mapping in scripts/calibration/import_labels.py (no API involved)."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from pareeksha.evaluation.rubric import DIMENSION_KEYS

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "calibration" / "import_labels.py"
_spec = importlib.util.spec_from_file_location("import_labels", SCRIPT)
assert _spec and _spec.loader
il = importlib.util.module_from_spec(_spec)
sys.modules["import_labels"] = il  # dataclasses look the module up while the class is created
_spec.loader.exec_module(il)

KEY = {"L01": "11111111-1111-1111-1111-111111111111", "L02": "22222222-2222-2222-2222-222222222222"}


def row(lid: str, **over: str) -> dict[str, str]:
    base = {"label_id": lid, "passed": "yes", "critical": "no", "notes": ""}
    base.update({d: "4" for d in il.DIMENSIONS})
    base.update(over)
    return base


def test_dimensions_match_rubric() -> None:
    assert tuple(il.DIMENSIONS) == tuple(DIMENSION_KEYS)


def test_valid_rows_map_to_review_bodies() -> None:
    labels = il.parse_labels(
        [row("L02", passed="No", critical="YES", escalation="0", notes=" loud "), row("L01")], KEY
    )
    by_id = {lab.label_id: lab for lab in labels}
    assert by_id["L02"].call_id == KEY["L02"]
    body = by_id["L02"].review_body("preetham")
    assert body == {
        "reviewer": "preetham",
        "passed": False,
        "critical_failure": True,
        "dimensions": {d: {"score": 0 if d == "escalation" else 4} for d in il.DIMENSIONS},
        "notes": "loud",
    }


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([row("L01")], "not labelled: L02"),
        ([row("L01"), row("L02"), row("L01")], "appears more than once"),
        ([row("L01"), row("L02"), row("L09")], "not in the key"),
        ([row("L01", passed="maybe"), row("L02")], "passed must be yes or no"),
        ([row("L01", critical=""), row("L02")], "critical must be yes or no"),
        ([row("L01", task_completion="5"), row("L02")], "task_completion must be an integer 0-4"),
        ([row("L01", empathy_tone="3.5"), row("L02")], "empathy_tone must be an integer 0-4"),
        ([row("L01", escalation=""), row("L02")], "escalation must be an integer 0-4"),
        ([row(""), row("L01"), row("L02")], "label_id is empty"),
    ],
)
def test_invalid_rows_are_rejected(rows: list[dict[str, str]], message: str) -> None:
    with pytest.raises(il.LabelError, match=message):
        il.parse_labels(rows, KEY)


def test_all_problems_reported_together() -> None:
    with pytest.raises(il.LabelError) as exc:
        il.parse_labels([row("L01", passed="?", factual_accuracy="9")], KEY)
    text = str(exc.value)
    assert "passed must be yes or no" in text
    assert "factual_accuracy must be an integer 0-4" in text
    assert "not labelled: L02" in text


def test_csv_and_key_round_trip(tmp_path: Path) -> None:
    labels_csv = tmp_path / "labels.csv"
    with labels_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=il.COLUMNS)
        w.writeheader()
        w.writerow(row("L01"))
        w.writerow(row("L02", passed="no"))
    key_file = tmp_path / ".key.json"
    key_file.write_text(json.dumps({"labels": {k: {"call_id": v} for k, v in KEY.items()}}))
    labels = il.parse_labels(il.read_csv(labels_csv), il.read_key(key_file))
    assert [(lab.label_id, lab.passed) for lab in labels] == [("L01", True), ("L02", False)]


def test_csv_missing_column(tmp_path: Path) -> None:
    p = tmp_path / "labels.csv"
    p.write_text("label_id,passed\nL01,yes\n", encoding="utf-8")
    with pytest.raises(il.LabelError, match="missing columns critical"):
        il.read_csv(p)


def test_disagreements() -> None:
    labels = il.parse_labels([row("L01", passed="no"), row("L02", conversation_flow="1")], KEY)
    judge = {d: {"score": 4} for d in il.DIMENSIONS}
    evaluations = {
        KEY["L01"]: {"passed": True, "critical_failure": False, "dimensions": judge},
        KEY["L02"]: {"passed": True, "critical_failure": False, "dimensions": judge},
    }
    found = {d.label_id: d for d in il.disagreements(labels, evaluations)}
    assert found["L01"].pass_fail and found["L01"].dimension_gaps == {}
    assert not found["L02"].pass_fail
    assert found["L02"].dimension_gaps == {"conversation_flow": (4, 1)}
    # a 1-point gap alone is not a disagreement
    labels = il.parse_labels([row("L01", empathy_tone="3"), row("L02")], KEY)
    assert il.disagreements(labels, evaluations) == []


# --- pass/fail-only mode (owner gave no 0-4 dimension scores) ---------------------------------


def pf_row(lid: str, passed: str = "no", critical: str = "no", notes: str = "") -> dict[str, str]:
    return {
        "label_id": lid,
        "passed": passed,
        "critical": critical,
        "notes": notes,
        **dict.fromkeys(il.DIMENSIONS, ""),
    }


def judge_row(passed: bool, critical: bool, score: float = 90.0) -> dict:
    return {
        "passed": passed,
        "critical_failure": critical,
        "overall_score": score,
        "summary": "s",
        "failure_types": [],
        "dimensions": {d: {"score": 4, "reason": "r"} for d in il.DIMENSIONS},
    }


def test_pass_fail_only_rows_parse_without_scores() -> None:
    labels = il.parse_labels([pf_row("L01", "yes"), pf_row("L02", critical="yes")], KEY)
    assert [lab.scores for lab in labels] == [{}, {}]
    assert il.label_mode(labels) == "pass_fail_only"
    assert labels[1].review_body("preetham")["dimensions"] == {}  # nothing invented for the API
    assert il.label_mode(il.parse_labels([row("L01"), row("L02")], KEY)) == "full"


def test_partly_filled_dimensions_still_rejected() -> None:
    with pytest.raises(il.LabelError, match="escalation must be an integer 0-4"):
        il.parse_labels([row("L01", escalation=""), pf_row("L02")], KEY)


def test_mixed_modes_rejected() -> None:
    with pytest.raises(il.LabelError, match="mixed modes"):
        il.parse_labels([row("L01"), pf_row("L02")], KEY)


def test_normalise_owner_rows() -> None:
    raw = [
        {
            "label_id": "L01",
            "passed": "fail",
            "critical": "yes",
            "task_completion": " no",
            "policy_compliance": "  o",
            "notes": "hallucination ",
        },
        {
            "label_id": "L02",
            "passed": "partial",
            "critical": "no",
            "factual_accuracy": "TRUE",
            "notes": "",
        },
        {
            "label_id": "L03",
            "passed": "passed",
            "critical": "yes",
            "escalation": "ok ",
            "notes": "",
        },
    ]
    out = il.normalise_owner_rows(raw)
    assert [(r["passed"], r["critical"]) for r in out] == [
        ("no", "yes"),
        ("no", "no"),
        ("yes", "yes"),
    ]
    assert all(r[d] == "" for r in out for d in il.DIMENSIONS)  # dropped, never converted
    assert out[0]["notes"] == "hallucination "


@pytest.mark.parametrize("passed", ["maybe", "", "yes"])
def test_normalise_owner_rejects_unknown_verdicts(passed: str) -> None:
    with pytest.raises(il.LabelError, match="passed"):
        il.normalise_owner_rows([{"label_id": "L01", "passed": passed, "critical": "no"}])


def test_identical_rows() -> None:
    rows = [
        pf_row("L01", notes="x"),
        pf_row("L02", notes="x"),
        pf_row("L03", notes="y"),
        pf_row("L04", notes="x"),
    ]
    assert il.identical_rows(rows) == [["L01", "L02", "L04"]]


def test_offline_calibration_matches_endpoint_function_pass_fail_only() -> None:
    from pareeksha.evaluation.calibration import cohen_kappa

    key = {f"L{i:02d}": f"c{i}" for i in range(1, 5)}
    labels = il.parse_labels(
        [
            pf_row("L01", "yes"),
            pf_row("L02", "no"),
            pf_row("L03", "no", "yes"),
            pf_row("L04", "yes"),
        ],
        key,
    )
    judge = {
        "c1": judge_row(True, False),
        "c2": judge_row(True, False),
        "c3": judge_row(False, True, 20),
        "c4": judge_row(True, False),
    }
    pairs = il.label_pairs(labels, judge)
    assert all(p.human_score is None and p.human_dimensions == {} for p in pairs)
    report = il.build_report(labels, judge, {"n": 4}, {"posted": 4}, None)
    off = report["calibration_offline"]
    assert off["kappa_pass_fail"] == round(
        cohen_kappa([True, True, False, True], [True, False, False, True]), 4
    )
    assert off["spearman_overall"] is None and off["dimension_mae"] == {}
    assert report["not_provided_by_owner"] == ["spearman_overall", "dimension_mae"]
    p = report["agreement"]["passed"]
    assert (
        p["judge_pass_human_pass"],
        p["judge_pass_human_fail"],
        p["judge_fail_human_pass"],
        p["judge_fail_human_fail"],
    ) == (2, 1, 0, 1)
    assert p["agreement"] == 0.75
    c = report["agreement"]["critical"]
    assert (c["judge_yes_human_yes"], c["judge_no_human_no"], c["agreement"]) == (1, 3, 1.0)
    assert [d["label_id"] for d in report["disagreements"]] == ["L02"]
    assert report["disagreements"][0]["dimension_gaps"] == {}


def test_render_md_marks_missing_metrics() -> None:
    key = {"L01": "c1", "L02": "c2"}
    labels = il.parse_labels([pf_row("L01", "yes"), pf_row("L02", "no", notes="bad | note")], key)
    judge = {"c1": judge_row(True, False), "c2": judge_row(True, False)}
    cal = {"n": 2, "kappa_pass_fail": None, "spearman_overall": None, "dimension_mae": {}}
    imported = {
        "reviewer": "preetham",
        "posted": 2,
        "already": 0,
        "labels": 2,
        "labels_file": "x.csv",
    }
    md = il.render_md(il.build_report(labels, judge, cal, imported, None), "## Plan\n\ntext")
    assert md.count(il.NOT_PROVIDED) >= 4
    assert "bad \\| note" in md
    assert md.rstrip().endswith("text")


# --- rows awaiting the owner (INTERIM) ----------------------------------------------------------


def blank(lid: str) -> dict[str, str]:
    return {"label_id": lid, **dict.fromkeys(il.COLUMNS[1:], "")}


def test_blank_rows_are_pending_not_errors() -> None:
    rows = [pf_row("L01", "yes"), blank("L02")]
    labels = il.parse_labels(rows, KEY)
    assert [lab.label_id for lab in labels] == ["L01"]
    assert il.pending_ids(rows) == ["L02"]
    # a row with only a note is not pending: it is an incomplete label
    with pytest.raises(il.LabelError, match="passed must be yes or no"):
        il.parse_labels([pf_row("L01", "yes"), {**blank("L02"), "notes": "x"}], KEY)


def test_parse_id_range() -> None:
    assert il.parse_id_range("L11-L13, L20") == {"L11", "L12", "L13", "L20"}
    assert il.parse_id_range("") == set()
    with pytest.raises(il.LabelError):
        il.parse_id_range("L11-12x")


def test_normalise_owner_blanks_unreviewed_rows() -> None:
    raw = [
        {"label_id": "L01", "passed": "fail", "critical": "yes", "notes": "a"},
        {"label_id": "L02", "passed": "fail", "critical": "yes", "notes": "a"},
    ]
    out = il.normalise_owner_rows(raw, {"L02"})
    assert out[0]["passed"] == "no"
    assert out[1] == blank("L02")
    assert il.pending_ids(out) == ["L02"]


def test_wilson_interval() -> None:
    assert il.wilson(10, 10) == (0.7225, 1.0)
    lo, hi = il.wilson(5, 10)
    assert lo < 0.5 < hi


def test_kappa_bootstrap_counts_undefined_resamples() -> None:
    jv = [True] + [False] * 9
    boot = il.kappa_bootstrap(jv, list(jv), n_boot=2000)
    assert boot["ci95"] == [1.0, 1.0]  # every defined resample agrees perfectly
    assert 0.2 < boot["undefined_share"] < 0.5  # resamples without the one pass: (9/10)^10 ~ 0.35
    assert il.kappa_bootstrap([False] * 4, [False] * 4, n_boot=50)["ci95"] is None


def test_interim_report() -> None:
    key = {"L01": "c1", "L02": "c2", "L03": "c3"}
    rows = [pf_row("L01", "yes"), pf_row("L02", "no"), blank("L03")]
    labels = il.parse_labels(rows, key)
    judge = {"c1": judge_row(True, False), "c2": judge_row(False, True, 30)}
    cal = {"n": 2, "kappa_pass_fail": 1.0, "spearman_overall": None, "dimension_mae": {}}
    imported = {
        "reviewer": "preetham",
        "posted": 2,
        "already": 0,
        "labels": 2,
        "labels_file": "x.csv",
    }
    report = il.build_report(labels, judge, cal, imported, None, il.pending_ids(rows), len(key))
    assert (report["interim"], report["labelled"], report["total"], report["pending"]) == (
        True,
        2,
        3,
        ["L03"],
    )
    md = il.render_md(report)
    assert md.startswith("# EVAL-06 calibration: judge vs owner labels (INTERIM)")
    assert "**INTERIM: 2 of 3 calls labelled.**" in md
    assert "not assessed (n = 2 < 30)" in md
    assert "Wilson CI" in md and "bootstrap" in md


def test_id_span() -> None:
    assert il._id_span([f"L{i}" for i in range(11, 31)]) == "L11-L30"
    assert il._id_span(["L01", "L03"]) == "L01, L03"
