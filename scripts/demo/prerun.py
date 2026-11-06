#!/usr/bin/env python3
"""DOC-03-REC pre-run: one failing run (planted bug) and the same cell against the clean agent. Real calls."""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "verify"))
import v04_planted_bugs as v4, vapi  # noqa: E402

BUG = sys.argv[1] if len(sys.argv) > 1 else "no_amount_confirm"
CELL = (["Promise to pay on Friday"], ["Manju — auto driver"], ["pstn_8k_alaw"])
out = {}
clean = next(a for a in vapi.items("/agents") if a["name"] == v4.CLEAN)
c = v4.start_container(BUG); v4.wait_ready(c)
try:
    agent = v4.register(BUG, c, clean)
    out["bug_run"] = vapi.run_and_wait(agent, *CELL, repeats=1, concurrency=1, name=f"demo-bug-{BUG}", poll_s=5)
finally:
    subprocess.run(["docker", "rm", "-f", c], capture_output=True)
out["clean_run"] = vapi.run_and_wait(v4.CLEAN, *CELL, repeats=1, concurrency=1, name="demo-clean", poll_s=5)
for k, r in out.items():
    it = r["items"][0]; ev = vapi.call(it["call_id"]).get("evaluation") or {}
    print(k, r["run_id"], it["call_id"], ev.get("passed"), ev.get("overall_score"), ev.get("critical_failure"), flush=True)
(ROOT / "proof/DOC-03/prerun.json").write_text(json.dumps({k: {"run_id": r["run_id"], "call_id": r["items"][0]["call_id"]} for k, r in out.items()}, indent=1))
