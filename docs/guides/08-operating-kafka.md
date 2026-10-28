# Guide 8 · Operating Kafka: topics, consumer lag, DLQ replay

Pareeksha is event-driven: the API writes rows and an outbox in one Postgres transaction, `outbox-relay` publishes to Kafka, and workers (consumer groups) do the work. This guide shows how to see what is happening and how to recover.

## 1. The pieces

| Component | Role |
|---|---|
| `kafka` (KRaft, single node) | event backbone; host listener on `localhost:${KAFKA_HOST_PORT:-9094}` |
| `kafka-init` | creates the topics (idempotent) from `infra/kafka/create-topics.sh` |
| `outbox-relay` | polls `outbox_events` and produces; at-least-once, so consumers dedupe |
| consumer groups | `planner`, `simulator`, `auditor`, `evaluator`, `finalizer`, `integrations`, `dialect`, `generator`, `retrier`, `dlq-recorder`, `reconciler` (a timer) |

Topics (all `pareeksha.<name>.v1`): `run.requested`, `call.requested` (key = run item), `audit.requested`, `call.completed`, `evaluation.completed`, `run.completed`, `progress`, `scenario.generate.requested`, `dialect.clip.requested`, plus `retry.30s`, `retry.5m` and `dlq`. Partitions default to 6 (`TOPIC_PARTITIONS`), retention 7 days (`TOPIC_RETENTION_HOURS`), DLQ 30 days. Simulators scale up to the partition count (`SIMULATOR_REPLICAS <= TOPIC_PARTITIONS`).

Failure handling per message: a transient error goes to `retry.30s` then `retry.5m`; a permanent error (malformed message, bad config) or the third failed attempt goes to `dlq`, where `dlq-recorder` stores it in the `dead_letters` table. An already-processed event is skipped (`processed_events`), so replays are safe.

## 2. List topics and consumer groups

```bash
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list | grep '^pareeksha\.'
docker compose exec kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --all-groups
```

Optional UI: `docker compose --profile tools up -d kafka-ui`, then <http://localhost:8080> (`KAFKA_UI_HOST_PORT`).

## 3. Consumer lag and health from the API

```bash
curl -s -H "Authorization: Bearer $PAREEKSHA_API_KEY" http://localhost:${API_HOST_PORT:-8000}/api/v1/metrics/summary
# {"consumer_lag":{"simulator":0,"evaluator":0,...},"outbox_backlog":0,"dlq_open":0,"credits_used":12.3}
pareeksha doctor        # same numbers, plus db/kafka reachability; exit 1 if either is down
```

How to read it:
- `consumer_lag[group]` = messages produced but not yet processed by that group. Brief non-zero lag during a run is normal; lag that keeps growing means the group is down or stuck: `docker compose logs --tail=50 <service>`, `docker compose restart <service>`.
- `outbox_backlog` > 0 for long: `outbox-relay` is down or Kafka is unreachable. Nothing is lost, the rows wait in Postgres.
- `dlq_open` > 0: something needs a human, see below.

## 4. Inspect and replay dead letters

```bash
pareeksha dlq list                       # id, original topic, attempts, error
pareeksha dlq replay <dead-letter-id>    # re-publish the stored envelope to its original topic
```

Via the API: `GET /dlq?status=open`, `POST /dlq/{id}/replay`, `POST /dlq/{id}/discard`. Replay keeps the original `event_id` and sets `attempt=1`; groups that already handled the event skip it, the one that failed tries again, and if it fails again the same row re-opens. Fix the cause first (rotate the expired HubSpot token, restore the dependency, correct the config), then replay; discard what cannot succeed.

The web app has the same list under DLQ.

**Drill (safe to run on a dev box):** put two bad messages on a topic and watch them land.

```bash
# 1. not JSON at all: goes straight to the DLQ and can only be discarded
echo "not-json" | docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server localhost:9092 --topic pareeksha.call.completed.v1
# 2. a valid envelope for a call that does not exist (attempt=3): permanent failure, replayable
python3 - > env.json <<'PY'
import json, uuid, datetime
print(json.dumps({"event_id": str(uuid.uuid4()), "type": "call.completed", "version": 1,
  "occurred_at": datetime.datetime.now(datetime.UTC).isoformat(), "correlation_id": "drill", "attempt": 3,
  "producer": "drill@cli", "payload": {"call_id": str(uuid.uuid4()), "source": "upload"}}))
PY
docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server localhost:9092 --topic pareeksha.call.completed.v1 < env.json
sleep 15; pareeksha dlq list
```

Replaying the first answers `409 ... not a valid event envelope and cannot be replayed`; discard it with `curl -X POST -H "Authorization: Bearer $PAREEKSHA_API_KEY" $API/dlq/<id>/discard`. Replaying the second re-publishes it; it fails the same way (the call still does not exist), so the row re-opens. That is the expected behaviour until the cause is fixed.

## 5. Recovery cheat sheet

| Situation | Action |
|---|---|
| Broker restarted | nothing: consumers reconnect, the outbox re-publishes (duplicates are deduped) |
| A worker crashed mid-message | the offset was not committed; the message is redelivered on restart |
| Run stuck with `active_calls` > 0 | the `reconciler` heals leaked slots every minute |
| Many DLQ entries after an outage | fix the dependency, then replay each with `pareeksha dlq replay` |
| Full reset of a dev box | `docker compose --profile workers down -v` (deletes Kafka and Postgres volumes) |

For a managed Kafka set `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_SECURITY_PROTOCOL=SASL_SSL`, `KAFKA_SASL_*` in `.env` and create the topics once with `infra/kafka/create-topics.sh`.
