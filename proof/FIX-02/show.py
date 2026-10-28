"""Print a compact table of a qa03.py result file (verdict, score, failed checks, review reasons)."""
import json, sys
d = json.load(open(sys.argv[1]))
s = d["summary"]
print(f"{d['label']}: run {d['run_id'][:8]} {d['status']} pass_rate={s['pass_rate']} critical={s['critical_failures']} mean={s['score_mean']}")
for c in d["calls"]:
    i, k = c["item"], c["call"] or {}
    ev = k.get("evaluation") or {}
    bad = [x.get("detail") for x in k.get("checks", []) if x.get("passed") is False]
    print(f"  {i['scenario'][:30]:30} {i['persona'][:18]:18} {i['status']:9} {i['overall_score']!s:6} pass={i['passed']} crit={i['critical_failure']} {ev.get('failure_types')} {bad}")
