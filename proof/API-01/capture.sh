#!/bin/sh
# Reproduces proof/API-01/migrate_and_tables.txt: real Alembic run in the compose `migrate`
# service against compose Postgres, then the tables as Postgres reports them.
# Sandbox behind a TLS-intercepting proxy:
#   COMPOSE_EXTRA="-f docker-compose.yml -f docker-compose.proxy.yml" CA_BUNDLE=/root/.ccr/ca-bundle.crt ./proof/API-01/capture.sh
set -u
cd "$(dirname "$0")/../.."
OUT=proof/API-01/migrate_and_tables.txt
C="docker compose ${COMPOSE_EXTRA:-}"
psqlc() { $C exec -T postgres psql -U pareeksha -d pareeksha "$@"; }
{
  $C up -d postgres --wait
  echo '$ docker compose run --rm migrate   (1st run, empty database)'
  $C run --rm migrate 2>&1 | grep -v ' Container '
  echo "exit=$(cd . && $C run --rm migrate >/dev/null 2>&1; echo $?)  [2nd run: already at head, must be 0]"
  echo
  echo '$ psql -c "\dt"'
  psqlc -c '\dt'
  echo '$ select * from alembic_version'
  psqlc -c 'select * from alembic_version'
  echo '$ table count (excluding alembic_version)'
  psqlc -c "select count(*) as tables from information_schema.tables where table_schema='public' and table_name <> 'alembic_version'"
  echo '$ \d api_keys'
  psqlc -c '\d api_keys'
  echo '$ partial indexes'
  psqlc -c "select indexname, indexdef from pg_indexes where indexname in ('one_active_rubric','outbox_unpublished','dead_letters_open')"
} > "$OUT" 2>&1
cat "$OUT"
