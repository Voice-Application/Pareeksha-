#!/bin/bash
# watch_run.sh <run_id> [seconds]: sample active_calls and item statuses every 3 s until the run ends
RUN=$1; PSQL="docker exec pk-m2b-postgres-1 psql -U pareeksha -d pareeksha -At"
while true; do
  row=$($PSQL -c "select now()::time(0), status, active_calls, (select string_agg(s||'='||n, ' ' order by s) from (select status s, count(*) n from run_items where run_id='$RUN' group by 1) q) from test_runs where id='$RUN'")
  echo "$row"
  case "$row" in *"|completed|"*|*"|partial|"*|*"|failed|"*|*"|cancelled|"*) break;; esac
  sleep 3
done
