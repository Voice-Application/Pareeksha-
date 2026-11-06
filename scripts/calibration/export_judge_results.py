#!/usr/bin/env python3
"""EVAL-06: dump the judge's stored results for the batch calls from Postgres to
proof/EVAL-06/judge_results.json (evaluations + deterministic checks, straight from the DB rows).

This file is evidence for the proof, NOT part of the blind labelling packet.

    COMPOSE="docker compose -f docker-compose.yml -f docker-compose.proxy.yml" \
        python3 scripts/calibration/export_judge_results.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "verify"))
import vapi  # noqa: E402

PROOF = ROOT / "proof" / "EVAL-06"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=Path, default=PROOF / "batch.json")
    ap.add_argument("--out", type=Path, default=PROOF / "judge_results.json")
    ap.add_argument(
        "--rubric-version", help="only this rubric's evaluations (a call has one row per version)"
    )
    args = ap.parse_args(argv)
    batch = [
        r
        for r in json.loads(args.batch.read_text())
        if r.get("evaluation_status") == "ok"
    ]
    rubric_filter = ""
    if args.rubric_version:
        if not all(c.isalnum() or c in "-_." for c in args.rubric_version):
            raise SystemExit(f"bad rubric version {args.rubric_version!r}")
        rubric_filter = f" AND rv.version = '{args.rubric_version}'"
    ids = ",".join(f"'{r['call_id']}'" for r in batch)  # uuids written by run_batch.py from the API
    query = f"""
    SELECT coalesce(json_agg(x ORDER BY x.call_id), '[]') FROM (
      SELECT e.call_id, e.id AS evaluation_id, rv.version AS rubric_version, e.judge_model, e.prompt_hash,
             e.status, e.overall_score, e.passed, e.critical_failure, e.needs_human_review, e.review_reasons,
             e.failure_types, e.dimensions, e.summary, e.confidence, e.temperature, e.input_tokens,
             e.output_tokens, e.latency_ms, e.created_at,
             (SELECT coalesce(json_agg(json_build_object('check_type', c.check_type, 'check_key', c.check_key,
                     'passed', c.passed, 'must_pass', c.must_pass, 'evidence_turns', c.evidence_turns,
                     'detail', c.detail) ORDER BY c.check_type, c.check_key), '[]')
                FROM deterministic_checks c WHERE c.call_id = e.call_id) AS checks
        FROM evaluations e JOIN rubric_versions rv ON rv.id = e.rubric_version_id
       WHERE e.call_id IN ({ids}){rubric_filter}
    ) x"""
    rows = json.loads(vapi.sql(query))
    by_call = {r["call_id"]: r for r in batch}
    for r in rows:
        b = by_call[r["call_id"]]
        r["batch"] = {
            k: b[k] for k in ("cell", "bug", "scenario", "persona", "noise_profile", "run_id")
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} evaluation rows for {len(batch)} calls -> {args.out}")
    ok = len({r["call_id"] for r in rows}) == len(batch) == len(rows)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
