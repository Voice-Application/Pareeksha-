#!/usr/bin/env python3
"""EVAL-06 step 3: import the owner's blind labels and compute judge-vs-human agreement.

Reads labelling/EVAL-06/labels.csv (filled by the owner) and labelling/EVAL-06/.key.json (label id ->
call id), validates every row, posts each one through the real human-review API
(POST /calls/{call_id}/review), then reads GET /calibration and writes
proof/EVAL-06/calibration.json and calibration.md (kappa, Spearman, per-dimension MAE, n, and the
calls where judge and human disagree).

    python3 scripts/calibration/import_labels.py [--labels PATH] [--key PATH] [--reviewer preetham]

Env: PAREEKSHA_API_URL, PAREEKSHA_API_KEY (or .env), as in scripts/verify/vapi.py.
A row already imported for this reviewer (409 from the API) is reported and left as it is.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "labelling" / "EVAL-06"
PROOF = ROOT / "proof" / "EVAL-06"

# rubric-2026-10-v1 (backend/pareeksha/seed/data/rubric-2026-10-v1.yaml), in rubric order.
DIMENSIONS = (
    "task_completion",
    "policy_compliance",
    "factual_accuracy",
    "language_handling",
    "conversation_flow",
    "empathy_tone",
    "escalation",
)
COLUMNS = ("label_id", "passed", "critical", *DIMENSIONS, "notes")
YES, NO = {"yes", "y", "true", "1"}, {"no", "n", "false", "0"}


class LabelError(ValueError):
    """Every problem found in the label file, one per line."""


@dataclass(frozen=True)
class Label:
    label_id: str
    call_id: str
    passed: bool
    critical: bool
    scores: dict[str, int]
    notes: str = ""

    def review_body(self, reviewer: str) -> dict[str, Any]:
        """Body of POST /calls/{call_id}/review (backend/pareeksha/schemas/calls.py ReviewCreate)."""
        return {
            "reviewer": reviewer,
            "passed": self.passed,
            "critical_failure": self.critical,
            "dimensions": {k: {"score": v} for k, v in self.scores.items()},
            "notes": self.notes,
        }


def _yes_no(value: str, column: str, where: str, problems: list[str]) -> bool:
    v = value.strip().lower()
    if v in YES:
        return True
    if v in NO:
        return False
    problems.append(f"{where}: {column} must be yes or no, got {value!r}")
    return False


def parse_labels(rows: list[dict[str, str]], key: dict[str, str]) -> list[Label]:
    """Validate the CSV rows against the key; raise LabelError listing every problem.

    Every key id must be labelled exactly once; passed/critical are yes/no; all seven dimension scores
    are integers 0-4 (the API needs all seven to compute the human overall score that Spearman uses).
    """
    problems: list[str] = []
    labels: list[Label] = []
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        lid = (row.get("label_id") or "").strip()
        where = f"line {line} ({lid or 'no label_id'})"
        if not lid:
            problems.append(f"{where}: label_id is empty")
            continue
        if lid not in key:
            problems.append(f"{where}: label_id is not in the key")
            continue
        if lid in seen:
            problems.append(f"{where}: label_id appears more than once")
            continue
        seen.add(lid)
        passed = _yes_no(row.get("passed") or "", "passed", where, problems)
        critical = _yes_no(row.get("critical") or "", "critical", where, problems)
        scores: dict[str, int] = {}
        for dim in DIMENSIONS:
            raw = (row.get(dim) or "").strip()
            if raw not in {"0", "1", "2", "3", "4"}:
                problems.append(f"{where}: {dim} must be an integer 0-4, got {raw!r}")
                continue
            scores[dim] = int(raw)
        labels.append(
            Label(lid, key[lid], passed, critical, scores, (row.get("notes") or "").strip())
        )
    missing = sorted(set(key) - seen)
    if missing:
        problems.append(f"not labelled: {', '.join(missing)}")
    if problems:
        raise LabelError("\n".join(problems))
    return labels


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = tuple(h.strip() for h in reader.fieldnames or ())
        absent = [c for c in COLUMNS if c not in header]
        if absent:
            raise LabelError(f"{path}: missing columns {', '.join(absent)}")
        return [{(k or "").strip(): v or "" for k, v in r.items()} for r in reader]


def read_key(path: Path) -> dict[str, str]:
    """``{"L01": "<call uuid>", ...}`` from the packet's .key.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping = data.get("labels", data)
    return {str(k): str(v["call_id"] if isinstance(v, dict) else v) for k, v in mapping.items()}


@dataclass
class Disagreement:
    label_id: str
    call_id: str
    judge_passed: bool | None
    human_passed: bool
    judge_critical: bool | None
    human_critical: bool
    dimension_gaps: dict[str, tuple[int, int]] = field(
        default_factory=dict
    )  # dim -> (judge, human)

    @property
    def pass_fail(self) -> bool:
        return self.judge_passed is not None and self.judge_passed != self.human_passed


def disagreements(
    labels: list[Label], evaluations: dict[str, dict[str, Any]], min_gap: int = 2
) -> list[Disagreement]:
    """Calls where judge and human differ on pass/fail or critical, or by >= ``min_gap`` on a dimension."""
    out: list[Disagreement] = []
    for lab in labels:
        ev = evaluations.get(lab.call_id) or {}
        dims = ev.get("dimensions") or {}
        gaps = {
            d: (int(dims[d]["score"]), lab.scores[d])
            for d in DIMENSIONS
            if isinstance(dims.get(d), dict)
            and abs(int(dims[d]["score"]) - lab.scores[d]) >= min_gap
        }
        d = Disagreement(
            lab.label_id,
            lab.call_id,
            ev.get("passed"),
            lab.passed,
            ev.get("critical_failure"),
            lab.critical,
            gaps,
        )
        if (
            d.pass_fail
            or (d.judge_critical is not None and d.judge_critical != d.human_critical)
            or gaps
        ):
            out.append(d)
    return out


class Api:
    def __init__(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts" / "verify"))
        import vapi

        self.base = vapi.api_url()
        self.token = vapi.setting("PAREEKSHA_API_KEY")

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        req = urllib.request.Request(
            self.base + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode()
                return r.status, json.loads(text) if text else None
        except urllib.error.HTTPError as exc:
            text = exc.read().decode()
            try:
                return exc.code, json.loads(text)
            except json.JSONDecodeError:
                return exc.code, text


def render_md(cal: dict[str, Any], imported: dict[str, Any], dis: list[Disagreement]) -> str:
    lines = [
        "# EVAL-06 calibration: judge vs owner labels",
        "",
        f"Source: `GET /calibration` after importing {imported['posted']} new review(s) "
        f"({imported['already']} already present) as reviewer `{imported['reviewer']}`.",
        "",
        "| metric | value |",
        "|---|---|",
        f"| n (labelled evaluations) | {cal.get('n')} |",
        f"| Cohen's kappa (pass/fail) | {cal.get('kappa_pass_fail')} |",
        f"| Spearman rho (overall score) | {cal.get('spearman_overall')} |",
    ]
    for d, mae in (cal.get("dimension_mae") or {}).items():
        lines.append(f"| MAE {d} | {mae} |")
    kappa = cal.get("kappa_pass_fail")
    verdict = "n/a" if kappa is None else ("meets" if kappa >= 0.6 else "below")
    lines += [
        "",
        f"Target (docs/08 section 10, V9): kappa >= 0.6 on >= 30 calls: **{verdict}**.",
        "",
        f"## Disagreements ({len(dis)})",
        "",
        "Pass/fail or critical differ, or a dimension differs by 2 or more (judge -> human).",
        "",
        "| label | call | pass judge/human | critical judge/human | dimension gaps |",
        "|---|---|---|---|---|",
    ]
    for d in dis:
        gaps = ", ".join(f"{k} {j}->{h}" for k, (j, h) in d.dimension_gaps.items()) or "-"
        lines.append(
            f"| {d.label_id} | `{d.call_id}` | {d.judge_passed}/{d.human_passed} | "
            f"{d.judge_critical}/{d.human_critical} | {gaps} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--labels", type=Path, default=PACKET / "labels.csv")
    ap.add_argument("--key", type=Path, default=PACKET / ".key.json")
    ap.add_argument("--reviewer", default="preetham")
    ap.add_argument("--out", type=Path, default=PROOF)
    args = ap.parse_args(argv)
    try:
        labels = parse_labels(read_csv(args.labels), read_key(args.key))
    except LabelError as exc:
        print(f"labels.csv is not valid, nothing was imported:\n{exc}", file=sys.stderr)
        return 2
    api = Api()
    posted, already, evaluations = 0, 0, {}
    for lab in labels:
        status, body = api.call(
            "POST", f"/calls/{lab.call_id}/review", lab.review_body(args.reviewer)
        )
        if status == 201:
            posted += 1
        elif status == 409 and "already reviewed" in json.dumps(body):
            already += 1
        else:
            print(
                f"{lab.label_id} ({lab.call_id}): POST review -> {status} {body}", file=sys.stderr
            )
            return 1
        status, call = api.call("GET", f"/calls/{lab.call_id}")
        if status != 200:
            print(f"{lab.label_id}: GET call -> {status} {call}", file=sys.stderr)
            return 1
        evaluations[lab.call_id] = call.get("evaluation") or {}
    status, cal = api.call("GET", "/calibration")
    if status != 200:
        print(f"GET /calibration -> {status} {cal}", file=sys.stderr)
        return 1
    imported = {
        "reviewer": args.reviewer,
        "posted": posted,
        "already": already,
        "labels": len(labels),
    }
    dis = disagreements(labels, evaluations)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "calibration.json").write_text(
        json.dumps(
            {
                "calibration": cal,
                "import": imported,
                "disagreements": [
                    {
                        **d.__dict__,
                        "dimension_gaps": {
                            k: {"judge": j, "human": h} for k, (j, h) in d.dimension_gaps.items()
                        },
                    }
                    for d in dis
                ],
            },
            indent=1,
        )
        + "\n"
    )
    (args.out / "calibration.md").write_text(render_md(cal, imported, dis))
    print(json.dumps({"calibration": cal, **imported, "disagreements": len(dis)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
