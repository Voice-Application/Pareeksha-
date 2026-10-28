"""Summarise the planted-bug runs: was the single call of each bug run flagged, and with which cited turns?"""
import json, sys
from pathlib import Path
rows = []
for f in sorted(Path(sys.argv[1]).glob("bug*.json")):
    d = json.load(open(f))
    for c in d["calls"]:
        i, k = c["item"], c["call"] or {}
        ev = k.get("evaluation") or {}
        cited = sorted({t for dm in ev.get("dimensions", {}).values() if dm["score"] < 3 for t in dm["evidence_turns"]})
        failed_checks = [x.get("detail") for x in k.get("checks", []) if x.get("passed") is False]
        flagged = bool(i["status"] == "evaluated" and (not i["passed"] or i["critical_failure"] or failed_checks or ev.get("failure_types")))
        rows.append({"bug": f.stem.split("-", 1)[1], "status": i["status"], "score": i["overall_score"], "passed": i["passed"], "critical": i["critical_failure"],
                     "failure_types": ev.get("failure_types"), "failed_checks": failed_checks, "cited_turns": cited, "flagged": flagged, "call_id": i.get("call_id")})
caught = sum(r["flagged"] for r in rows)
out = {"bugs_caught": caught, "of": len(rows), "calls": rows}
Path(sys.argv[1], "..", "catch_report.json").resolve().write_text(json.dumps(out, indent=1))
for r in rows: print(r["bug"].ljust(20), "FLAGGED" if r["flagged"] else "missed ", r["score"], r["failure_types"], r["failed_checks"], "turns", r["cited_turns"])
print(f"caught {caught}/{len(rows)}")
