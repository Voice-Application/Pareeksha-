#!/usr/bin/env python3
"""EVAL-08: re-judge the calls whose 'company' disclosure check ran with the first draft of the rule
(within the first 2 agent turns) after the rule was widened to the whole call (owner rule R-a: "never
says which company is calling"). Only those calls can change: the widening affects nothing else.

For each call in the batch files whose company check says "first 2 agent turns", POST
/calls/{id}/reevaluate (same rubric, same evaluation row) and wait until the check is recomputed.

    python3 scripts/calibration/rejudge_company.py proof/EVAL-06/batch.json proof/EVAL-07/heldout_batch.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "verify"))
import vapi  # noqa: E402

OLD = "first 2 agent turns"


def company(cid: str) -> dict:
    checks = vapi.call(cid).get("checks") or []
    return next((c for c in checks if c["check_key"] == "company"), {})


def main(argv: list[str]) -> int:
    ids = [
        r["call_id"]
        for f in argv
        for r in json.loads(Path(f).read_text())
        if r.get("evaluation_status") == "ok"
    ]
    todo = [cid for cid in ids if OLD in company(cid).get("detail", "")]
    print(f"{len(todo)} of {len(ids)} calls have the old company check", flush=True)
    for cid in todo:
        vapi.request("POST", f"/calls/{cid}/reevaluate", {})
    pending, t0 = set(todo), time.time()
    while pending and time.time() - t0 < 1800:
        for cid in sorted(pending):
            c = company(cid)
            ev = vapi.call(cid).get("evaluation") or {}
            if c and OLD not in c["detail"] and ev.get("status") in ("ok", "judge_error"):
                pending.discard(cid)
                print(
                    f"{cid} company passed={c['passed']} ({c['detail']}) -> "
                    f"{ev['rubric_version']} passed={ev.get('passed')} score={ev.get('overall_score')}",
                    flush=True,
                )
        if pending:
            time.sleep(10)
    print(f"re-judged {len(todo) - len(pending)}/{len(todo)}")
    return 0 if not pending else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
