#!/usr/bin/env bash
# V9 (FR-EV-7, FR-EV-8, NFR-6, NFR-7): judge vs Preetham's labels on 30 calls: n = 30, Cohen's kappa >= 0.6, and kappa
# recomputed independently from the exported labels. The labels are the owner's; PENDING until 30 exist.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 9 "Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6"
$PY - <<'PYEOF' | tee "$OUT/V9.json" | block
import json, sys
sys.path.insert(0, "scripts/verify")
import vapi
cal = vapi.request("GET", "/calibration")
rows = vapi.sql("SELECT e.passed, h.passed FROM human_reviews h JOIN evaluations e ON e.id = h.evaluation_id "
                "WHERE e.status='ok' AND e.passed IS NOT NULL")
pairs = [tuple(x == "t" for x in r.split("|")) for r in rows.splitlines() if r]
n = len(pairs)
def kappa(p):
    if not p: return None
    po = sum(a == b for a, b in p) / len(p)
    pj = sum(a for a, _ in p) / len(p); ph = sum(b for _, b in p) / len(p)
    pe = pj * ph + (1 - pj) * (1 - ph)
    return None if pe == 1 else (po - pe) / (1 - pe)
mine = kappa(pairs)
res = {"api": cal, "labelled_pairs_in_db": n, "kappa_recomputed": mine}
print(json.dumps(res, indent=1))
if n < 30: sys.exit(2)
ok = cal.get("n", 0) >= 30 and (cal.get("kappa_pass_fail") or 0) >= 0.6 and mine is not None and abs(mine - cal["kappa_pass_fail"]) < 0.02
sys.exit(0 if ok else 1)
PYEOF
rc=${PIPESTATUS[0]}
[ "$rc" -eq 0 ] && finish PASS "kappa >= 0.6 on >= 30 labelled calls, recomputed independently"
[ "$rc" -eq 2 ] && finish PENDING "fewer than 30 human-labelled calls (EVAL-06 needs Preetham's labels)"
finish FAIL "kappa below 0.6 or API/recomputed values disagree"
