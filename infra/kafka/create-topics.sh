#!/usr/bin/env bash
# Idempotently create Pareeksha topics. Run by the kafka-init container.
# Source of truth must match backend/pareeksha/events/topics.py (TL-owned contract).
set -euo pipefail

BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}"
PARTITIONS="${TOPIC_PARTITIONS:-6}"
RF="${TOPIC_REPLICATION_FACTOR:-1}"
RETENTION_MS=$(( ${TOPIC_RETENTION_HOURS:-168} * 3600 * 1000 ))
KT=/opt/kafka/bin/kafka-topics.sh

echo "Waiting for Kafka at ${BOOTSTRAP}..."
until "$KT" --bootstrap-server "$BOOTSTRAP" --list >/dev/null 2>&1; do sleep 2; done

create() {  # name partitions retention_ms
  "$KT" --bootstrap-server "$BOOTSTRAP" --create --if-not-exists \
    --topic "$1" --partitions "$2" --replication-factor "$RF" \
    --config "retention.ms=$3" --config "cleanup.policy=delete"
}

create pareeksha.run.requested.v1                "$PARTITIONS" "$RETENTION_MS"
create pareeksha.call.requested.v1               "$PARTITIONS" "$RETENTION_MS"   # key = run_item_id
create pareeksha.audit.requested.v1              "$PARTITIONS" "$RETENTION_MS"
create pareeksha.call.completed.v1               "$PARTITIONS" "$RETENTION_MS"
create pareeksha.evaluation.completed.v1         "$PARTITIONS" "$RETENTION_MS"
create pareeksha.run.completed.v1                3             "$RETENTION_MS"
create pareeksha.progress.v1                     3             86400000          # 1 day
create pareeksha.scenario.generate.requested.v1  3             "$RETENTION_MS"
create pareeksha.dialect.clip.requested.v1       "$PARTITIONS" "$RETENTION_MS"
create pareeksha.retry.30s.v1                    3             "$RETENTION_MS"
create pareeksha.retry.5m.v1                     3             "$RETENTION_MS"
create pareeksha.dlq.v1                          3             $(( 30 * 86400000 ))  # 30 days

echo "Topics:"
"$KT" --bootstrap-server "$BOOTSTRAP" --list | grep '^pareeksha\.'
