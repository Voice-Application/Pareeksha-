#!/usr/bin/env bash
# Run the Kafka suite against a running Kafka + Postgres, exactly as the kafka-suite workflow does.
#
#   docker compose up -d kafka postgres && docker compose up kafka-init
#   scripts/ci/kafka_suite.sh
#
# Defaults match docker-compose.yml. Override for another stack:
#   INFRA_TEST_KAFKA_BOOTSTRAP   broker address as seen from the host      (localhost:9094)
#   TEST_DATABASE_URL            Postgres server for throw-away databases   (localhost:5432)
#   INFRA_TEST_DATABASE_URL      database for the INFRA-02 plumbing tests
# The outage test finds the broker container by the host port in INFRA_TEST_KAFKA_BOOTSTRAP.
# Extra arguments are passed to pytest.
set -euo pipefail
cd "$(dirname "$0")/../../backend"
exec python3 -m pytest tests/kafka tests/integration -p no:cacheprovider -rs \
  --cov=pareeksha --cov-report=term "$@"
