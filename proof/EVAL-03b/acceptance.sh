#!/usr/bin/env bash
# EVAL-03b live acceptance: evaluator + finalizer containers (compose profile "workers") on real
# Kafka + Postgres with ONE real DeepSeek judge call (DEEPSEEK_API_KEY from the environment/.env).
# Sandbox: TLS-intercepting proxy overlay, Postgres remapped to 55432 (5432 was taken).
#   ./proof/EVAL-03b/acceptance.sh \
#     > proof/EVAL-03b/acceptance.txt 2>&1   (OVERRIDE defaults to proof/EVAL-03b/sandbox_override.yml)
set -uo pipefail
export COMPOSE_PROJECT_NAME=eval03b CA_BUNDLE=${CA_BUNDLE:-/root/.ccr/ca-bundle.crt} BUILDX_BAKE_ENTITLEMENTS_FS=0
export COST_DEEPSEEK_PER_1K_INPUT_TOKENS=0.00132 COST_DEEPSEEK_PER_1K_OUTPUT_TOKENS=0.00396   # v4-pro list price
PGPORT=${PGPORT:-55432}
OVERRIDE=${OVERRIDE:-proof/EVAL-03b/sandbox_override.yml}
C="docker compose -f docker-compose.yml -f docker-compose.proxy.yml -f $OVERRIDE"
step() { echo; echo "=== $(date -u +%H:%M:%S) $*"; }

step "stack: kafka, postgres, topics"
$C up -d kafka postgres && $C up kafka-init 2>&1 | tail -2
step "migrate (Alembic) and seed (rubric rubric-2026-10-v1, demo agent) inside the backend image"
$C up --build migrate 2>&1 | tail -4
$C run --rm migrate python -m pareeksha.seed 2>&1 | grep -v -E "Demo API key|PAREEKSHA_API_KEY" | head -20
step "start the worker groups at the current end of their topics (earlier test traffic is not replayed)"
PYTHONPATH=backend python3 - <<'PY'
import asyncio
from pareeksha.events.topics import Topics
from tests.integration.support import prime_group
async def main() -> None:
    await prime_group("evaluator", [Topics.CALL_COMPLETED])
    await prime_group("finalizer", [Topics.EVALUATION_COMPLETED])
    print("primed: evaluator, finalizer")
asyncio.run(main())
PY
step "start evaluator (2 replicas) and finalizer containers"
$C --profile workers up -d --build evaluator finalizer 2>&1 | tail -6
sleep 15
$C --profile workers ps
step "acceptance: seed one run/one call, publish call.completed twice, one real DeepSeek call"
PYTHONPATH=backend DATABASE_URL="postgresql://pareeksha:pareeksha@localhost:${PGPORT}/pareeksha" \
  KAFKA_BOOTSTRAP_SERVERS=localhost:9094 \
  INFRA_TEST_DATABASE_URL="postgresql://pareeksha:pareeksha@localhost:${PGPORT}/pareeksha_events_test" \
  python3 proof/EVAL-03b/acceptance.py
step "worker logs (evaluator + finalizer)"
$C --profile workers logs --no-log-prefix evaluator finalizer 2>&1 | grep -v -E '^\s*$' | tail -40
step "consumer group lag"
$C exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group evaluator --group finalizer 2>&1 | head -30
