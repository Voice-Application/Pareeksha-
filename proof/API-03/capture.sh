#!/usr/bin/env bash
# Reproduces proof/API-03/e2e.txt on the compose stack: API container -> Postgres (run + outbox in
# one transaction) -> outbox-relay container -> Kafka -> planner container (consumer group
# `planner`) -> run_items + call.requested; then the run-slot cap, the reconciler container healing
# a leaked slot, and cancel.
#
# Sandbox notes: another project on this host holds 5432/9094/8000, so proof/API-03/compose.override.yml
# remaps Postgres to 35432, Kafka (host listener) to 39094 and the API to 38000; behind a TLS-
# intercepting proxy set CA_BUNDLE (the proxy overlay builds the images with it).
# Usage (repo root): ./proof/API-03/capture.sh > proof/API-03/e2e.txt 2>&1
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=proof/API-03
FILES=(-f docker-compose.yml -f "$OUT/compose.override.yml")
if [ -n "${CA_BUNDLE:-}" ]; then FILES=(-f docker-compose.yml -f docker-compose.proxy.yml -f "$OUT/compose.override.yml"); fi
export BUILDX_BAKE_ENTITLEMENTS_FS=0
DC=(docker compose -p api03 "${FILES[@]}")
KEY="pk_live_proof-api03-throwaway-key-0001"
API=http://localhost:38000/api/v1
PSQL=("${DC[@]}" exec -T postgres psql -U pareeksha -d pareeksha -P pager=off)
KAFKA_BIN=/opt/kafka/bin

section() { printf '\n===== %s =====\n' "$1"; }
sql() { "${PSQL[@]}" -c "$1"; }
call() { curl -s -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' "$@"; }
pretty() { python3 -m json.tool; }

section "stack"
"${DC[@]}" up -d kafka postgres
"${DC[@]}" up kafka-init 2>&1 | tail -1
"${DC[@]}" up -d --build api
"${DC[@]}" exec -T -e PAREEKSHA_API_KEY="$KEY" api python -m pareeksha.seed | tail -12
"${DC[@]}" --profile workers up -d --build outbox-relay planner reconciler
sleep 5
"${DC[@]}" ps --format 'table {{.Service}}\t{{.Status}}'

section "POST /runs (3 scenarios x 2 personas x 2 noise profiles = 12 calls, max_concurrency 3)"
ids() { call "$API/$1?limit=$2" | python3 -c "import sys,json; print(json.dumps([i['id'] for i in json.load(sys.stdin)['items']]))"; }
AGENT=$(call "$API/agents" | python3 -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")
BODY=$(python3 - <<EOF
import json
print(json.dumps({"agent_id": "$AGENT", "name": "API-03 proof", "kind": "matrix",
  "scenario_ids": $(ids scenarios 3), "persona_ids": $(ids personas 2),
  "noise_profile_ids": $(ids noise-profiles 2), "repeats": 1,
  "config": {"max_concurrency": 3, "seed": 42}}))
EOF
)
RESPONSE=$(call -X POST "$API/runs" -d "$BODY")
echo "$RESPONSE" | pretty
RUN_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "RUN_ID=$RUN_ID"

section "POST /runs:estimate (same body, creates nothing)"
call -X POST "$API/runs:estimate" -d "$BODY" | pretty

for _ in $(seq 1 40); do
  [ "$(sql "SELECT count(*) FROM run_items WHERE run_id = '$RUN_ID'" | sed -n 3p | tr -d ' ')" = "12" ] && break
  sleep 1
done

section "outbox row for the run (written in the same transaction; published by outbox-relay)"
sql "SELECT topic, key, published_at IS NOT NULL AS published, attempts, envelope->>'event_id' AS event_id, envelope->>'producer' AS producer FROM outbox_events WHERE key = '$RUN_ID'"

section "run row"
sql "SELECT id, status, kind, active_calls, config->>'max_concurrency' AS cap, config->>'item_count' AS item_count, estimated_cost FROM test_runs WHERE id = '$RUN_ID'"

section "run_items created by the planner (the 12 calls)"
sql "SELECT i.id AS run_item_id, left(s.title, 28) AS scenario, left(p.name, 22) AS persona, n.name AS noise_profile, i.seed, i.status FROM run_items i JOIN scenarios s ON s.id = i.scenario_id JOIN personas p ON p.id = i.persona_id JOIN noise_profiles n ON n.id = i.noise_profile_id WHERE i.run_id = '$RUN_ID' ORDER BY i.id"

section "Kafka: call.requested for this run (key = run_item_id) with partition / offset"
"${DC[@]}" exec -T kafka $KAFKA_BIN/kafka-console-consumer.sh --bootstrap-server kafka:9092 \
  --topic pareeksha.call.requested.v1 --from-beginning --timeout-ms 8000 \
  --property print.key=true --property print.partition=true --property print.offset=true 2>/dev/null \
  | python3 -c "
import sys, json
rows = []
for line in sys.stdin:
    fields = line.rstrip('\n').split('\t')
    if len(fields) != 4:
        continue
    partition, offset, key, value = fields
    env = json.loads(value)
    if env['payload']['run_id'] == '$RUN_ID':
        rows.append((f'{partition} {offset}', key, env))
print(f'{len(rows)} call.requested messages for run $RUN_ID')
for meta, key, env in sorted(rows, key=lambda r: r[1]):
    print(f\"{meta:22} key={key} event_id={env['event_id']} causation={env['causation_id'][:8]}.. seed={env['payload']['seed']}\")
"

section "Kafka: consumer group planner (offsets / lag on pareeksha.run.requested.v1)"
"${DC[@]}" exec -T kafka $KAFKA_BIN/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group planner 2>&1 | grep -E "GROUP|run.requested" | sort -u

section "planner container log"
"${DC[@]}" logs planner 2>&1 | grep -E "planned run|processed" | tail -3

section "run slots: 12 simulators race for the slots of this run (cap 3)"
"${DC[@]}" run --rm -T -v "$PWD/$OUT:/proof:ro" api python /proof/slots_demo.py "$RUN_ID" 2>&1 | grep -v Container

section "leak a slot, let the reconciler container heal it (runs every 60 s)"
sql "UPDATE test_runs SET active_calls = 7 WHERE id = '$RUN_ID'"
sql "SELECT active_calls AS active_calls_after_leak, (SELECT count(*) FROM run_items WHERE run_id = test_runs.id AND status IN ('connecting','in_progress')) AS really_active FROM test_runs WHERE id = '$RUN_ID'"
for _ in $(seq 1 80); do
  [ "$(sql "SELECT active_calls FROM test_runs WHERE id = '$RUN_ID'" | sed -n 3p | tr -d ' ')" = "3" ] && break
  sleep 1
done
sql "SELECT active_calls AS active_calls_after_reconcile FROM test_runs WHERE id = '$RUN_ID'"
"${DC[@]}" logs reconciler 2>&1 | grep "repaired" | tail -2

section "GET /runs/{id} and /items (progress and joined names)"
call "$API/runs/$RUN_ID" | python3 -c "import sys,json; r=json.load(sys.stdin); print(json.dumps({k: r[k] for k in ('id','status','kind','progress','estimated_cost')}, indent=2))"
call "$API/runs/$RUN_ID/items?limit=3" | python3 -c "import sys,json; r=json.load(sys.stdin); print(json.dumps(r['items'], indent=1)[:900]); print('next_cursor set:', bool(r['next_cursor']))"
call "$API/runs?limit=5" | python3 -c "import sys,json; print('GET /runs ->', [(r['id'][:8], r['status']) for r in json.load(sys.stdin)['items']])"

section "POST /runs/{id}/cancel (queued items cancelled, the 3 in-flight calls are left to finish)"
call -X POST "$API/runs/$RUN_ID/cancel" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['status'], r['progress'])"
sql "SELECT status, count(*) FROM run_items WHERE run_id = '$RUN_ID' GROUP BY status ORDER BY 1"
call -X POST "$API/runs/$RUN_ID/cancel" -w '\nsecond cancel -> HTTP %{http_code}\n'

section "consumer group offsets after everything"
"${DC[@]}" exec -T kafka $KAFKA_BIN/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group planner 2>&1 | grep -E "GROUP|run.requested" | sort -u
echo
echo "commit: $(git rev-parse --short HEAD)"
