"""Detection table for the 5 planted bugs from results/*.json (signature = what the platform flagged)."""
import json
from pathlib import Path

R = Path(__file__).parent / "results"
load = lambda n: json.loads((R / f"{n}.json").read_text())

def flags(call):
    e = call["evaluation"] or {}
    fts = set(e.get("failure_types") or [])
    chk = {c["check_key"]: c for c in call["checks"] if c["passed"] is False}
    dims = {k: v for k, v in (e.get("dimensions") or {}).items()}
    return e, fts, chk, dims

SIG = {  # bug -> (result file, paired clean file, predicate -> (hit, cited turns, why))
 "no_disclosure": ("bug1-no_disclosure", "clean-a"),
 "no_amount_confirm": ("bug2-no_amount_confirm", "clean-a"),
 "english_to_kannada": ("bug3b-english_to_kannada", "clean-d"),
 "ignore_interrupt": ("bug4-ignore_interrupt", "clean-b"),
 "false_waiver": ("bug5-false_waiver", "clean-c"),
}
def hit(bug, call):
    e, fts, chk, dims = flags(call)
    if bug == "no_disclosure":
        c = chk.get("recording")
        return (bool(c) or "missing_disclosure" in fts, c["evidence_turns"] if c else dims["policy_compliance"]["evidence_turns"], "disclosure check failed / missing_disclosure")
    if bug == "no_amount_confirm":
        d = dims["task_completion"]
        return (d["score"] <= 2, d["evidence_turns"], "task_completion<=2: " + d["reason"][:110])
    if bug == "english_to_kannada":
        c = next((v for v in chk.values() if v["check_type"] == "language_match"), None)
        return ("language_mismatch" in fts or bool(c), c["evidence_turns"] if c else dims["language_handling"]["evidence_turns"], "language_match check failed / language_mismatch")
    if bug == "ignore_interrupt":
        return ("interruption_handling" in fts, dims["conversation_flow"]["evidence_turns"], "interruption_handling failure type")
    if bug == "false_waiver":
        return ("policy_violation" in fts, dims["policy_compliance"]["evidence_turns"], "policy_violation failure type")

out, caught = {}, 0
for bug, (bf, cf) in SIG.items():
    rows = []
    for x in load(bf)["calls"]:
        h, turns, why = hit(bug, x["call"])
        e = x["call"]["evaluation"]
        rows.append({"call_id": x["call"]["id"], "flagged": bool(h), "cited_turns": turns, "why": why,
                     "passed": e["passed"], "critical_failure": e["critical_failure"], "score": e["overall_score"]})
    clean_rows = [bool(hit(bug, x["call"])[0]) for x in load(cf)["calls"]]
    n = sum(r["flagged"] for r in rows)
    ok = n * 2 > len(rows) or n == len(rows)  # caught = more than half of its calls flagged
    caught += ok
    out[bug] = {"run": load(bf)["run_id"], "flagged": f"{n}/{len(rows)}", "caught": ok,
                "paired_clean_run": load(cf)["run_id"], "clean_signature_hits": f"{sum(clean_rows)}/{len(clean_rows)}", "calls": rows}
clean = {}
for name in ("clean-a", "clean-b", "clean-c", "clean-d", "clean-e"):
    r = load(name); cs = [x["call"]["evaluation"] for x in r["calls"]]
    clean[name] = {"run": r["run_id"], "passed": f"{sum(1 for e in cs if e['passed'])}/{len(cs)}"}
res = {"bugs_caught": caught, "of": 5, "per_bug": out, "clean_runs": clean}
Path(__file__).with_name("catch_report.json").write_text(json.dumps(res, indent=1))
print(f"caught {caught}/5")
for b, v in out.items():
    print(f"{b:20} flagged {v['flagged']:4} caught={v['caught']!s:5} clean-signature-hits {v['clean_signature_hits']}  cited {[r['cited_turns'] for r in v['calls']]}")
print({k: v["passed"] for k, v in clean.items()})
