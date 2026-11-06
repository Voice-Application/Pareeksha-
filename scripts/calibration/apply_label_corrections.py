#!/usr/bin/env python3
"""EVAL-08: apply an owner's label corrections and post them through the real review API.

The owner's original labels stay verbatim (``labels.owner.json``). A corrections file lists
``{label_id, passed, critical, reason}``. This script:
  1. rewrites those rows of ``labels.csv`` (passed / critical; the reason is appended to notes);
  2. posts a new review for each corrected call, POST /calls/{id}/review. The API allows one review per
     reviewer per evaluation, and GET /calibration uses the NEWEST review per evaluation, so the
     correction is posted as reviewer ``<reviewer>-correction-<date>`` and supersedes the original,
     which is kept;
  3. refuses to finish unless GET /calibration still counts --expect-n evaluations (one per
     evaluation, so a correction does not grow it).

    python3 scripts/calibration/apply_label_corrections.py --labels labelling/EVAL-08/labels.csv \\
        --key labelling/EVAL-08/.key.json --corrections labelling/EVAL-08/labels.owner.corrections.json \\
        --reviewer preetham-correction-2026-11-03 --expect-n 75
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "import_labels", HERE / "import_labels.py"
)
assert _spec and _spec.loader
il = importlib.util.module_from_spec(_spec)
sys.modules["import_labels"] = il
_spec.loader.exec_module(il)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--key", type=Path, required=True)
    ap.add_argument("--corrections", type=Path, required=True)
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--expect-n", type=int, required=True)
    args = ap.parse_args(argv)

    fixes = {
        c["label_id"]: c
        for c in json.loads(args.corrections.read_text(encoding="utf-8"))
    }
    with args.labels.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields, rows = list(reader.fieldnames or []), list(reader)
    unknown = set(fixes) - {r["label_id"] for r in rows}
    if unknown:
        print(f"corrections for unknown rows: {sorted(unknown)}", file=sys.stderr)
        return 2
    for r in rows:
        c = fixes.get(r["label_id"])
        if c is None:
            continue
        before = (r["passed"], r["critical"])
        r["passed"], r["critical"] = c["passed"], c["critical"]
        if c["reason"] not in r["notes"]:
            r["notes"] = (r["notes"].strip() + " | " if r["notes"].strip() else "") + c[
                "reason"
            ]
        print(
            f"{r['label_id']}: passed/critical {before} -> {(r['passed'], r['critical'])}"
        )
    with args.labels.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    key = il.read_key(args.key)
    labels = {
        lab.label_id: lab for lab in il.parse_labels(il.read_csv(args.labels), key)
    }
    api = il.Api()
    for lid in fixes:
        lab = labels[lid]
        status, body = api.call(
            "POST", f"/calls/{lab.call_id}/review", lab.review_body(args.reviewer)
        )
        if status == 409 and "already reviewed" in json.dumps(body):
            print(f"{lid}: correction already posted (409)")
        elif status != 201:
            print(f"{lid}: POST review -> {status} {body}", file=sys.stderr)
            return 1
        else:
            print(
                f"{lid}: correction posted as {args.reviewer} (201), passed={lab.passed}"
            )
    status, cal = api.call("GET", "/calibration")
    n = (cal or {}).get("n")
    print(
        f"GET /calibration: n={n} kappa_pass_fail={(cal or {}).get('kappa_pass_fail')}"
    )
    if status != 200 or n != args.expect_n:
        print(
            f"expected n={args.expect_n} from GET /calibration, got {n}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
