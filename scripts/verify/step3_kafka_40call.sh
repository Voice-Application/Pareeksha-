#!/usr/bin/env bash
# NFR-3, NFR-4c: 5 scenarios x 4 personas x 2 noise profiles = 40 calls; >= 95% of run_items not in 'error';
# Kafka consumer lag per group at the end; DLQ count. Appends to proof/verify/V3.md.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
STEP=3; EVID="$OUT/V3.md"; [ -f "$EVID" ] || begin 3 "Kafka runs"
res=$($PY - <<'PYEOF'
import json, sys
sys.path.insert(0, "scripts/verify")
import vapi
scen = [s["title"] for s in vapi.items("/scenarios")][:5]
pers = [p["name"] for p in vapi.items("/personas")][:4]
prof = [n["name"] for n in vapi.items("/noise-profiles")][:2]
out = vapi.run_and_wait("EMI Reminder Bot", scen, pers, prof, repeats=1, concurrency=4, name="verify-40-call")
print(json.dumps({"run_id": out["run_id"], "wall_s": out["wall_s"]}))
PYEOF
)
run_id=$(echo "$res" | $PY -c 'import json,sys; print(json.load(sys.stdin)["run_id"])' 2>/dev/null)
note "## 40-call Kafka run"; echo "$res" | block
[ -n "$run_id" ] || { note "FAIL: run did not start"; exit 1; }
psql_q "SELECT status, count(*) FROM run_items WHERE run_id='$run_id' GROUP BY 1 ORDER BY 1" | block
total=$(psql_q "SELECT count(*) FROM run_items WHERE run_id='$run_id'")
infra=$(psql_q "SELECT count(*) FROM run_items WHERE run_id='$run_id' AND status='error'")
$COMPOSE exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --all-groups 2>/dev/null > "$OUT/V3.consumer_lag.txt" || true
lag=$(awk 'NR>1 && $6 ~ /^[0-9]+$/ {s+=$6} END{print s+0}' "$OUT/V3.consumer_lag.txt")
dlq=$(psql_q "SELECT count(*) FROM dead_letters" 2>/dev/null || echo "?")
note "Items: $total, infra errors: $infra, total consumer lag: $lag (proof/verify/V3.consumer_lag.txt), dead letters: $dlq"
ratio_ok=$(awk "BEGIN{print ($total>0 && ($total-$infra)/$total >= 0.95) ? 1 : 0}")
if [ "$total" -eq 40 ] && [ "$ratio_ok" -eq 1 ] && [ "$lag" -eq 0 ]; then note "PASS"; exit 0; fi
note "FAIL: need 40 items, >= 95% without infra error, lag 0"; exit 1
