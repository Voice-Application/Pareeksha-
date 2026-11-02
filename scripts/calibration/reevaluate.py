#!/usr/bin/env python3
"""EVAL-07: re-evaluate already-judged calls with the build's active rubric (no new speech).

For every call in a batch file, POST /calls/{id}/reevaluate (the evaluator judges with the active
rubric, now rubric-2026-10-v2, and adds a new evaluation row; the old rubric's row is kept), then
wait until the call's latest evaluation is the expected rubric version.

    python3 scripts/calibration/reevaluate.py --batch proof/EVAL-06/batch.json --rubric rubric-2026-10-v2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "verify"))
import vapi  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--rubric", required=True, help="the version the evaluator is expected to use")
    ap.add_argument("--timeout-s", type=int, default=1800)
    args = ap.parse_args(argv)
    ids = [r["call_id"] for r in json.loads(args.batch.read_text()) if r.get("evaluation_status") == "ok"]
    for cid in ids:
        if (vapi.call(cid).get("evaluation") or {}).get("rubric_version") != args.rubric:
            vapi.request("POST", f"/calls/{cid}/reevaluate", {})
    t0, pending = time.time(), set(ids)
    while pending and time.time() - t0 < args.timeout_s:
        for cid in sorted(pending):
            ev = vapi.call(cid).get("evaluation") or {}
            if ev.get("rubric_version") == args.rubric and ev.get("status") in ("ok", "judge_error"):
                pending.discard(cid)
                print(f"{cid} {ev['status']} passed={ev.get('passed')} score={ev.get('overall_score')}", flush=True)
        if pending:
            time.sleep(10)
    print(f"re-evaluated {len(ids) - len(pending)}/{len(ids)} with {args.rubric} in {time.time() - t0:.0f}s")
    return 0 if not pending else 1


if __name__ == "__main__":
    raise SystemExit(main())
