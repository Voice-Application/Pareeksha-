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
