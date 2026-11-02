#!/usr/bin/env python3
"""EVAL-06: dump the judge's stored results for the batch calls from Postgres to
proof/EVAL-06/judge_results.json (evaluations + deterministic checks, straight from the DB rows).

This file is evidence for the proof, NOT part of the blind labelling packet.

    COMPOSE="docker compose -f docker-compose.yml -f docker-compose.proxy.yml" \
        python3 scripts/calibration/export_judge_results.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "verify"))
import vapi  # noqa: E402

PROOF = ROOT / "proof" / "EVAL-06"


def main() -> int:
    batch = [
        r
        for r in json.loads((PROOF / "batch.json").read_text())
        if r.get("evaluation_status") == "ok"
    ]
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
       WHERE e.call_id IN ({ids})
    ) x"""
    rows = json.loads(vapi.sql(query))
    by_call = {r["call_id"]: r for r in batch}
    for r in rows:
        b = by_call[r["call_id"]]
        r["batch"] = {
            k: b[k] for k in ("cell", "bug", "scenario", "persona", "noise_profile", "run_id")
        }
    (PROOF / "judge_results.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rows)} evaluation rows for {len(batch)} calls -> {PROOF / 'judge_results.json'}")
    return 0 if len({r["call_id"] for r in rows}) == len(batch) else 1


if __name__ == "__main__":
    raise SystemExit(main())
