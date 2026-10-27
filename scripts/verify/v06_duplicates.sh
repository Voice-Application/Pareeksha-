#!/usr/bin/env bash
# V6 (NFR-4, FR-IN-5): the Kafka suite, then a live replay: re-publish one real evaluation.completed event twice and
# SIGKILL the integrations worker mid-flight; there must still be exactly one evaluation for the call and at most one
# delivery per (integration, event). Needs a finished run (V2/V3 create one).
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 6 "Duplicate delivery and worker crash give one evaluation and one CRM note"
# The suite publishes to the same topics the stack's workers consume, so the workers are stopped while it runs.
WORKERS="outbox-relay planner simulator auditor evaluator finalizer integrations dialect generator retrier dlq-recorder reconciler"
pgport=$(grep -E '^POSTGRES_HOST_PORT=' .env | cut -d= -f2 | cut -d' ' -f1); kport=$(grep -E '^KAFKA_HOST_PORT=' .env | cut -d= -f2 | cut -d' ' -f1)
$COMPOSE --profile workers stop $WORKERS >/dev/null 2>&1
(set -o pipefail; cd backend && DATABASE_URL="postgresql+psycopg://pareeksha:pareeksha@localhost:${pgport:-5432}/pareeksha" \
  INFRA_TEST_KAFKA_BOOTSTRAP="localhost:${kport:-9094}" KAFKA_BOOTSTRAP_SERVERS="localhost:${kport:-9094}" python3 -m pytest tests/kafka -q -p no:cacheprovider 2>&1 | tail -15) > "$OUT/V6.kafka_suite.txt"
suite=$?
$COMPOSE --profile workers up -d $WORKERS >/dev/null 2>&1
sleep 20
block < "$OUT/V6.kafka_suite.txt"
# One fresh call, so its evaluation.completed is delivered to the sink integration while it exists.
$PY - <<'PYEOF' 2>&1 | block
import sys; sys.path.insert(0, "scripts/verify")
import vapi
scen = [s["title"] for s in vapi.items("/scenarios")][:1]
pers = [p["name"] for p in vapi.items("/personas")][:1]
prof = [n["name"] for n in vapi.items("/noise-profiles")][:1]
res = vapi.run_and_wait("EMI Reminder Bot", scen, pers, prof, name="v6-one-call")
print({"run_id": res["run_id"], "wall_s": res["wall_s"], "items": [i["status"] for i in res["items"]]})
PYEOF
sleep 30
[ "$(psql_q "SELECT count(*) FROM evaluations")" -gt 0 ] || finish FAIL "no evaluation in the database to replay"

call_id=$(psql_q "SELECT call_id FROM evaluations WHERE status='ok' ORDER BY created_at DESC LIMIT 1")
before_eval=$(psql_q "SELECT count(*) FROM evaluations WHERE call_id='$call_id'")
sink_before=$([ -n "${V6_SINK_LOG:-}" ] && grep -c "\"call_id\": \"$call_id\"" "$V6_SINK_LOG" || true)
note "sink hits before replay: $sink_before"
before_del=$(psql_q "SELECT count(*) FROM integration_deliveries")
sink_log=${V6_SINK_LOG:-}
$COMPOSE exec -T api python - "$call_id" <<'PYEOF' 2>&1 | block
import asyncio, json, sys
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
async def main(call_id):
    s = EventSettings.from_env()
    cons = AIOKafkaConsumer(Topics.EVALUATION_COMPLETED.value, bootstrap_servers=s.bootstrap_servers, group_id=None,
                            auto_offset_reset="earliest", enable_auto_commit=False, consumer_timeout_ms=15000)
    await cons.start()
    prod = AIOKafkaProducer(bootstrap_servers=s.bootstrap_servers)
    await prod.start()
    sent = 0
    try:
        async for m in cons:
            if json.loads(m.value)["payload"].get("call_id") == call_id:
                for _ in range(2):
                    await prod.send_and_wait(m.topic, m.value, key=m.key, headers=m.headers)
                    sent += 1
                break
    finally:
        await cons.stop(); await prod.stop()
    print(f"re-published the original evaluation.completed {sent} time(s)")
asyncio.run(main(sys.argv[1]))
PYEOF
$COMPOSE kill -s KILL integrations >/dev/null 2>&1; $COMPOSE up -d integrations >/dev/null 2>&1
sleep 45
after_eval=$(psql_q "SELECT count(*) FROM evaluations WHERE call_id='$call_id'")
dup_del=$(psql_q "SELECT count(*) FROM (SELECT integration_id, event_id, direction FROM integration_deliveries GROUP BY 1,2,3 HAVING count(*)>1) t")
dup_notes=$(psql_q "SELECT count(*) FROM (SELECT integration_id, external_id FROM integration_deliveries WHERE external_id IS NOT NULL GROUP BY 1,2 HAVING count(*)>1) t")
sink_hits=$([ -n "$sink_log" ] && grep -c "\"call_id\": \"$call_id\"" "$sink_log" || true)
note "webhook sink receiver hits for this call: $sink_hits"
note "call $call_id: evaluations before/after = $before_eval/$after_eval; deliveries before=$before_del; duplicate delivery keys=$dup_del; duplicate CRM note ids=$dup_notes"
[ "$suite" -eq 0 ] || finish FAIL "Kafka suite failed"
[ "$after_eval" -eq 1 ] && { [ "$sink_hits" = n/a ] || [ "$sink_hits" -eq 1 ]; } && [ "$dup_del" -eq 0 ] && [ "$dup_notes" -eq 0 ] && finish PASS "one evaluation, no duplicate delivery after replay x2 and SIGKILL"
finish FAIL "evaluations=$after_eval duplicate deliveries=$dup_del duplicate notes=$dup_notes"
