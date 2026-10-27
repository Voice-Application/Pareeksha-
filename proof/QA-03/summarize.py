"""Print a compact per-call verdict table for results/*.json."""
import json, sys, glob
for f in sorted(glob.glob(sys.argv[1] if len(sys.argv)>1 else "results/*.json")):
    r = json.load(open(f))
    print("==", r["label"], r["agent"], r["status"], r["progress"])
    for x in r["calls"]:
        c = x["call"]
        if not c: print("  no call", x["item"]["status"]); continue
        e = c.get("evaluation") or {}
        bad = [(k["check_key"], k["evidence_turns"]) for k in c["checks"] if k["passed"] is False]
        dims = {k: (v["score"], v["evidence_turns"]) for k, v in (e.get("dimensions") or {}).items() if v["score"] <= 2}
        print(f"  {x['item']['persona'][:14]:14} pass={e.get('passed')} crit={e.get('critical_failure')} score={e.get('overall_score')} ft={e.get('failure_types')} failed_checks={bad} low_dims={dims}")
