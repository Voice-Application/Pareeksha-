#!/usr/bin/env bash
# V6 (NFR-4, FR-IN-5): the Kafka suite, then a live replay: re-publish one real evaluation.completed event twice and
# SIGKILL the integrations worker mid-flight; there must still be exactly one evaluation for the call and at most one
# delivery per (integration, event). Needs a finished run (V2/V3 create one).
# The step starts its own local HTTPS webhook-sink receiver (self-signed, PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1 for the
# integrations worker) and registers a webhook integration pointing at it, so the replay is observed from the outside:
# the sink must receive exactly one delivery for the call. V6_SINK_PORT (default 18443) picks the port.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 6 "Duplicate delivery and worker crash give one evaluation and one CRM note"
SINK_DIR=$(mktemp -d); SINK_LOG="$SINK_DIR/sink.jsonl"; SINK_PORT=${V6_SINK_PORT:-18443}; : > "$SINK_LOG"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=host.docker.internal" \
  -addext "subjectAltName=DNS:host.docker.internal,DNS:localhost,IP:127.0.0.1" \
  -keyout "$SINK_DIR/key.pem" -out "$SINK_DIR/cert.pem" >/dev/null 2>&1
cat "${CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}" "$SINK_DIR/cert.pem" > "$SINK_DIR/trust.pem"
cat > "$SINK_DIR/override.yml" <<YML
services:
  integrations:
    extra_hosts: ["host.docker.internal:host-gateway"]
    environment: { PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS: "1", SSL_CERT_FILE: /sink-trust.pem, REQUESTS_CA_BUNDLE: /sink-trust.pem }
    volumes: ["$SINK_DIR/trust.pem:/sink-trust.pem:ro"]
YML
$PY scripts/verify/webhook_sink.py "$SINK_PORT" "$SINK_DIR/cert.pem" "$SINK_DIR/key.pem" "$SINK_LOG" &
SINK_PID=$!
trap 'kill $SINK_PID 2>/dev/null' EXIT
COMPOSE="$COMPOSE -f $SINK_DIR/override.yml"; export COMPOSE
$COMPOSE --profile workers up -d integrations >/dev/null 2>&1
note "local HTTPS webhook sink: https://host.docker.internal:$SINK_PORT (pid $SINK_PID, log kept in this step's evidence below)"
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
$PY - "$SINK_PORT" <<'PYEOF' 2>&1 | block
import sys, time, uuid; sys.path.insert(0, "scripts/verify")
import vapi
integ = vapi.request("POST", "/integrations", {"connector": "webhook", "name": f"v6-sink-{int(time.time())}",
    "config": {"url": f"https://host.docker.internal:{sys.argv[1]}/hook", "events": ["evaluation.completed"]},
    "secrets": {"signing_secret": uuid.uuid4().hex}})
test = vapi.request("POST", f"/integrations/{integ['id']}/test")
print({"integration": integ["id"], "test": test})
PYEOF
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
sink_hits_of() { $PY - "$SINK_LOG" "$1" <<'PYEOF'
import json, sys
n = 0
for line in open(sys.argv[1]):
    try:
        rec = json.loads(line)
    except ValueError:
        continue
    if sys.argv[2] in json.dumps(rec["body"]) and "evaluation.completed" in json.dumps(rec["body"]):
        n += 1
print(n)
PYEOF
}
sink_before=$(sink_hits_of "$call_id")
note "sink hits before replay: $sink_before"
before_del=$(psql_q "SELECT count(*) FROM integration_deliveries")
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
sink_hits=$(sink_hits_of "$call_id")
note "sink log lines (all): $(wc -l < "$SINK_LOG")"; head -c 1500 "$SINK_LOG" | block
note "webhook sink receiver hits for this call: $sink_hits"
note "call $call_id: evaluations before/after = $before_eval/$after_eval; deliveries before=$before_del; duplicate delivery keys=$dup_del; duplicate CRM note ids=$dup_notes"
[ "$suite" -eq 0 ] || finish FAIL "Kafka suite failed"
[ "$after_eval" -eq 1 ] && [ "$sink_hits" -eq 1 ] && [ "$dup_del" -eq 0 ] && [ "$dup_notes" -eq 0 ] && finish PASS "one evaluation, no duplicate delivery after replay x2 and SIGKILL"
finish FAIL "evaluations=$after_eval duplicate deliveries=$dup_del duplicate notes=$dup_notes"
