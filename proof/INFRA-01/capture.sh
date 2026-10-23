#!/usr/bin/env bash
# Reproduce: ./proof/INFRA-01/capture.sh > proof/INFRA-01/health.txt   (run from repo root, stack already up)
# Set CA_BUNDLE and add "-f docker-compose.proxy.yml" only when behind a TLS-intercepting proxy.
C="docker compose ${COMPOSE_EXTRA:-}"
echo '$ docker compose ps -a'; $C ps -a
echo; echo '$ curl -i localhost:8000/health'; curl -s -i localhost:8000/health
echo; echo '$ curl localhost:8765/health'; curl -s localhost:8765/health
echo; echo '$ curl -I localhost:3000'; curl -sI localhost:3000 | head -1
echo; echo '$ docker compose logs kafka-init'; $C logs kafka-init
echo; echo '$ docker compose logs migrate'; $C logs migrate
echo; echo '$ kafka-topics --describe'; $C exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe | grep '^Topic'
echo; echo '$ pg_isready'; $C exec -T postgres pg_isready -U pareeksha
echo; echo '$ docker compose run --rm kafka-init   (idempotent re-run)'; $C run --rm kafka-init | tail -14; echo "exit=${PIPESTATUS[0]}"
echo; echo '$ broker api versions via host listener :9094'; $C exec -T kafka /opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9094 | head -1
