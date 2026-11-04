#!/usr/bin/env bash
# V9 (FR-EV-7, FR-EV-8, NFR-6, NFR-7): judge vs Preetham's labels on 30 calls: n = 30, Cohen's kappa >= 0.6, and kappa
# recomputed independently from the exported labels. The labels are the owner's. Without 30 in the running database (no
# stack, or a fresh one) it applies the same criteria to the final run recorded in proof/EVAL-06/calibration.json and says
# so; PENDING only when that is missing too. To re-run: restore proof/EVAL-06/pareeksha_db.sql.gz from task/EVAL-06.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 9 "Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6"
$PY - <<'PYEOF' | tee "$OUT/V9.json" | block
import hashlib, json, os, sys
sys.path.insert(0, "scripts/verify")
import vapi
def kappa(p):
    if not p: return None
    po = sum(a == b for a, b in p) / len(p)
    pj = sum(a for a, _ in p) / len(p); ph = sum(b for _, b in p) / len(p)
    pe = pj * ph + (1 - pj) * (1 - ph)
    return None if pe == 1 else (po - pe) / (1 - pe)
source, cal, pairs = "database", None, []
try:
    cal = vapi.request("GET", "/calibration")
    rows = vapi.sql("SELECT e.passed, h.passed FROM human_reviews h JOIN evaluations e ON e.id = h.evaluation_id "
                    "WHERE e.status='ok' AND e.passed IS NOT NULL")
    pairs = [tuple(x == "t" for x in r.split("|")) for r in rows.splitlines() if r]
except (Exception, SystemExit) as exc:
    source = f"database not reachable ({type(exc).__name__})"
if len(pairs) < 30:
    path = "proof/EVAL-06/calibration.json"
    # the recorded result counts only while it is the file task/EVAL-06 7d347ba produced
    raw = open(path, encoding="utf-8").read().encode() if os.path.exists(path) else b""  # text mode: same hash on CRLF checkouts
    rec = json.loads(raw) if hashlib.sha256(raw).hexdigest() == "21d3cca3844cd14a71c084357158f5d9b7176cd4843ea240e2b72c9e8d76464c" else None
    if not rec or rec["interim"] or rec["labelled"] < 30:
        print(json.dumps({"source": source, "labelled_pairs_in_db": len(pairs), "recorded_run": path if rec else None}, indent=1))
        sys.exit(2)
    a = rec["agreement"]["passed"]
    pairs = ([(True, True)] * a["judge_pass_human_pass"] + [(True, False)] * a["judge_pass_human_fail"]
             + [(False, True)] * a["judge_fail_human_pass"] + [(False, False)] * a["judge_fail_human_fail"])
    cal, source = rec["calibration_api"], f"recorded run {path}, not re-run here; {source}, {len(pairs)} pairs in it"
mine = kappa(pairs)
print(json.dumps({"source": source, "api": cal, "labelled_pairs_in_db": len(pairs), "kappa_recomputed": mine}, indent=1))
api_kappa = cal.get("kappa_pass_fail")
if mine is None or api_kappa is None or abs(mine - api_kappa) >= 0.02: sys.exit(3)
sys.exit(0 if cal.get("n", 0) >= 30 and api_kappa >= 0.6 else 4)
PYEOF
rc=${PIPESTATUS[0]}
[ "$rc" -eq 2 ] && finish PENDING "fewer than 30 human-labelled calls in this database and no unchanged final recorded run"
if [ "$rc" -eq 0 ] || [ "$rc" -eq 3 ] || [ "$rc" -eq 4 ]; then
  m=$($PY -c "import json; d = json.load(open('proof/verify/V9.json')); print(d['api']['kappa_pass_fail'], 'on n =', d['api']['n'], '(recorded EVAL-06 run, not re-run here)' if d['source'].startswith('recorded') else '')"); m=${m% }
fi
[ "$rc" -eq 0 ] && finish PASS "kappa $m meets the target, recomputed independently"
[ "$rc" -eq 3 ] && finish FAIL "API and recomputed kappa disagree or are undefined: $m"
[ "$rc" -eq 4 ] && finish FAIL "kappa $m is below the 0.6 target"
finish FAIL "the step could not run (exit $rc, see the output above)"
