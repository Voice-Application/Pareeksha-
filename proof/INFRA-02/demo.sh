#!/usr/bin/env bash
# INFRA-02 live demo against the compose stack (real Kafka + Postgres, real worker containers).
# Run from the repo root with kafka, postgres and kafka-init already up:
#   docker compose up -d kafka postgres && docker compose up kafka-init
#   ./proof/INFRA-02/demo.sh > proof/INFRA-02/demo.txt 2>&1        # takes about 7 minutes
# Sandbox (TLS-intercepting proxy, 5432 taken):
#   export COMPOSE_PROJECT_NAME=infra02 PGPORT=55432 CA_BUNDLE=/root/.ccr/ca-bundle.crt
#   export COMPOSE_EXTRA="-f docker-compose.yml -f docker-compose.proxy.yml -f <override that remaps postgres to \$PGPORT>"
set -uo pipefail
C="docker compose ${COMPOSE_EXTRA:-}"
PGPORT="${PGPORT:-5432}"
export PYTHONPATH=backend KAFKA_BOOTSTRAP_SERVERS=localhost:9094
export DATABASE_URL="postgresql+psycopg://pareeksha:pareeksha@localhost:${PGPORT}/pareeksha"
KBIN="$C exec -T kafka /opt/kafka/bin"
SQL() { $C exec -T postgres psql -U pareeksha -d pareeksha -c "$1"; }
step() { echo; echo "=== $(date -u +%H:%M:%S) $*"; }
groups() {
  $KBIN/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --all-groups 2>/dev/null |
    awk '$1=="GROUP" { if (!h) { print; h=1 } next } $1=="retrier" || $1=="dlq-recorder" || $1=="demo-flaky" { print }'
}

step "apply the Kafka plumbing tables (outbox_events, processed_events, dead_letters) from docs/schema.sql"
INFRA_TEST_DATABASE_URL="postgresql://pareeksha:pareeksha@localhost:${PGPORT}/pareeksha" \
  python -c "from tests.integration.support import prepare_database; prepare_database()" && echo applied
SQL "\dt"

step "start the three worker groups at the current end of their topics (so earlier test traffic is not replayed)"
python - <<'PY'
import asyncio
from pareeksha.events.topics import Topics
from tests.integration.support import prime_group
async def main() -> None:
    await prime_group("retrier", [Topics.RETRY_30S, Topics.RETRY_5M])
    await prime_group("dlq-recorder", [Topics.DLQ])
    await prime_group("demo-flaky", [Topics.AUDIT_REQUESTED])
    print("primed: retrier, dlq-recorder, demo-flaky")
asyncio.run(main())
PY

step "build and start the worker containers: outbox-relay, retrier, dlq-recorder"
$C --profile workers up -d --build outbox-relay retrier dlq-recorder 2>&1 | tail -8
sleep 8
$C ps outbox-relay retrier dlq-recorder

step "1. outbox: enqueue 5 events in one DB transaction; the relay container publishes them"
python proof/INFRA-02/enqueue_events.py 5
sleep 3
SQL "SELECT count(*) FILTER (WHERE published_at IS NULL) AS unpublished, count(*) FILTER (WHERE published_at IS NOT NULL) AS published FROM outbox_events"
$C logs --no-log-prefix outbox-relay 2>&1 | tail -3

step "2. REAL Kafka outage: stop the broker, enqueue 3 events (the DB write still works), then restart the broker"
$C stop kafka 2>&1 | tail -1
python proof/INFRA-02/enqueue_events.py 3
sleep 30   # longer than the producer request timeout, so the relay records the failure
SQL "SELECT count(*) FILTER (WHERE published_at IS NULL) AS unpublished, max(attempts) AS max_attempts, max(left(last_error, 60)) AS last_error FROM outbox_events"
$C logs --no-log-prefix outbox-relay 2>&1 | grep -cE "outbox publish failed|backing off" | sed 's/^/relay backoff warnings logged: /'
$C start kafka 2>&1 | tail -1
for i in $(seq 1 40); do
  n=$($C exec -T postgres psql -U pareeksha -d pareeksha -Atc "SELECT count(*) FROM outbox_events WHERE published_at IS NULL")
  [ "$n" = "0" ] && break; sleep 3
done
echo "unpublished after broker restart: $n (waited ~$((i*3))s)"
SQL "SELECT count(*) FILTER (WHERE published_at IS NULL) AS unpublished, count(*) AS total FROM outbox_events"

step "3. retry + DLQ with the real delays: a consumer that always fails (group demo-flaky), real retrier + dlq-recorder containers"
ENQ=$(python proof/INFRA-02/enqueue_events.py 1)
echo "$ENQ"
EVENT_ID=$(echo "$ENQ" | sed -E 's/.*event_id=([^ ]+) .*/\1/')
KEY=$(echo "$ENQ" | sed -E 's/.*key=([^ ]+).*/\1/')
python proof/INFRA-02/demo_consumer.py > proof/INFRA-02/demo_consumer.log 2>&1 &
CONSUMER_PID=$!
start=$(date +%s)
for i in $(seq 1 200); do
  n=$($C exec -T postgres psql -U pareeksha -d pareeksha -Atc "SELECT count(*) FROM dead_letters WHERE consumer_group='demo-flaky' AND key='$KEY'")
  [ "$n" -ge 1 ] && break; sleep 3
done
echo "dead letter recorded after $(( $(date +%s) - start ))s"
echo "--- handler calls for this event (the retry delays are the gaps between the timestamps):"
grep -h "$EVENT_ID" proof/INFRA-02/demo_consumer.log
echo "--- dead_letters:"
SQL "SELECT consumer_group, original_topic, attempts, status, left(error, 60) AS error FROM dead_letters WHERE consumer_group='demo-flaky' AND key='$KEY'"
echo "--- consumer-group offsets and lag (all groups used in this demo):"
groups
for t in retry.30s retry.5m dlq; do
  echo "--- pareeksha.$t.v1 (headers + key + attempt):"
  $KBIN/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic pareeksha.$t.v1 --from-beginning \
    --timeout-ms 5000 --property print.headers=true --property print.key=true 2>/dev/null \
    | grep "$KEY" | sed -E 's/"payload":\{[^}]*\}/"payload":{...}/'
done

step "4. graceful shutdown (SIGTERM): consumer on the host, worker containers"
kill -TERM $CONSUMER_PID; wait $CONSUMER_PID; echo "demo consumer exit code: $?"
$C stop retrier dlq-recorder outbox-relay 2>&1 | tail -3
for s in retrier dlq-recorder outbox-relay; do
  echo "$s exit code: $(docker inspect -f '{{.State.ExitCode}}' "$($C ps -a -q $s)")"
done
step "done"
