#!/usr/bin/env bash
# NFR-1: 20 calls, concurrency 4, < 15 min. Appends to proof/verify/V3.md. Exit 0 pass, 1 fail.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
STEP=3; EVID="$OUT/V3.md"; [ -f "$EVID" ] || begin 3 "Kafka runs"
res=$($PY - <<'PYEOF'
import json, sys
sys.path.insert(0, "scripts/verify")
import vapi
scen = [s["title"] for s in vapi.items("/scenarios")][:5]
pers = [p["name"] for p in vapi.items("/personas")][:2]
prof = [n["name"] for n in vapi.items("/noise-profiles")][:2]
out = vapi.run_and_wait("EMI Reminder Bot", scen, pers, prof, repeats=1, concurrency=4, name="verify-20-call")
done = sum(1 for i in out["items"] if i["status"] == "evaluated")
print(json.dumps({"run_id": out["run_id"], "wall_s": out["wall_s"], "items": len(out["items"]), "evaluated": done}))
PYEOF
)
note "## 20-call performance run"; echo "$res" | block
wall=$(echo "$res" | $PY -c 'import json,sys; print(json.load(sys.stdin)["wall_s"])' 2>/dev/null || echo 99999)
n=$(echo "$res" | $PY -c 'import json,sys; print(json.load(sys.stdin)["items"])' 2>/dev/null || echo 0)
if [ "$n" -eq 20 ] && awk "BEGIN{exit !($wall < 900)}"; then note "PASS: ${wall}s < 900s"; exit 0; fi
note "FAIL: items=$n wall=${wall}s (need 20 items, < 900s)"; exit 1
