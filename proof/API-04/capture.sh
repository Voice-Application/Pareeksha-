#!/usr/bin/env bash
# Reproduces proof/API-04/e2e.txt on the compose stack (private project `api04`, own ports):
# API container + outbox-relay + planner + dlq-recorder containers, real Postgres and Kafka.
# Runs are created through the API (planner makes the items); their results (calls, turns,
# evaluations) are seeded by seed_results.py because the simulator / evaluator workers are other
# tasks. Every API answer is printed next to the database rows it must match.
#
# Usage (repo root, with the pytest suite NOT running against the same broker):
#   CA_BUNDLE=/root/.ccr/ca-bundle.crt ./proof/API-04/capture.sh > proof/API-04/e2e.txt 2>&1
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=proof/API-04
FILES=(-f docker-compose.yml -f "$OUT/compose.override.yml")
if [ -n "${CA_BUNDLE:-}" ]; then FILES=(-f docker-compose.yml -f docker-compose.proxy.yml -f "$OUT/compose.override.yml"); fi
export BUILDX_BAKE_ENTITLEMENTS_FS=0
DC=(docker compose -p api04 "${FILES[@]}")
KEY="pk_live_proof-api04-throwaway-key-0001"
API=http://localhost:61800/api/v1
PSQL=("${DC[@]}" exec -T postgres psql -U pareeksha -d pareeksha -P pager=off)
KAFKA_BIN=/opt/kafka/bin
RUNTIME=data/runtime/proof/api04

section() { printf '\n===== %s =====\n' "$1"; }
sql() { "${PSQL[@]}" -c "$1"; }
sqlv() { "${PSQL[@]}" -tA -c "$1"; }
call() { curl -s -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' "$@"; }
pj() { python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(eval(sys.argv[1]) if len(sys.argv)>1 else d, indent=1, ensure_ascii=False))" "$@"; }
wait_for() { # wait_for <seconds> <command...>: poll until the command succeeds
  local n=$1; shift
  for _ in $(seq 1 "$n"); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done
  echo "TIMEOUT waiting for: $*"; return 1
}
wait_eval() { # wait_eval <seconds> '<shell condition>'
  for _ in $(seq 1 "$1"); do eval "$2" >/dev/null 2>&1 && return 0; sleep 1; done
  echo "TIMEOUT waiting for: $2"; return 1
}
dl_status() { sqlv "SELECT status FROM dead_letters WHERE id = '$DL'"; }
open_dl_count() { sqlv "SELECT count(*) FROM dead_letters WHERE status = 'open' AND consumer_group = 'planner'"; }
items_planned() { [ "$(sqlv "SELECT count(*) FROM run_items WHERE run_id = '$1'")" = "$2" ]; }
body_for() { python3 - "$@" <<'EOF'
import json, sys
name, scen, pers, prof = sys.argv[1:5]
print(json.dumps({"agent_id": sys.argv[5], "name": name, "kind": "matrix",
  "scenario_ids": json.loads(scen), "persona_ids": json.loads(pers),
  "noise_profile_ids": json.loads(prof), "repeats": 1, "config": {"max_concurrency": 3, "seed": 7}}))
EOF
}

section "stack (fresh: volumes removed so the broker and database hold only this capture)"
"${DC[@]}" --profile workers down -v --remove-orphans 2>&1 | tail -1
"${DC[@]}" up -d kafka postgres
"${DC[@]}" up kafka-init 2>&1 | tail -1
"${DC[@]}" up -d --build api
"${DC[@]}" exec -T -e PAREEKSHA_API_KEY="$KEY" api python -m pareeksha.seed | tail -8
"${DC[@]}" --profile workers up -d --build outbox-relay planner dlq-recorder
sleep 6
"${DC[@]}" ps --format 'table {{.Service}}\t{{.Status}}'

AGENT=$(call "$API/agents" | python3 -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")
ids() { call "$API/$1?limit=$2" | python3 -c "import sys,json; print(json.dumps([i['id'] for i in json.load(sys.stdin)['items']]))"; }
SCEN=$(ids scenarios 3); PERS=$(ids personas 1); PROF=$(ids noise-profiles 2)
new_run() { call -X POST "$API/runs" -d "$(body_for "$1" "$SCEN" "$PERS" "$PROF" "$AGENT")" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])"; }

section "two runs created through POST /runs (3 scenarios x 1 persona x 2 noise profiles = 6 calls each)"
RUN_A=$(new_run "API-04 base"); wait_for 60 items_planned "$RUN_A" 6
RUN_B=$(new_run "API-04 head"); wait_for 60 items_planned "$RUN_B" 6
echo "base RUN_A=$RUN_A"; echo "head RUN_B=$RUN_B"

section "seed the results of both runs (calls, turns, tool call, metrics, checks, evaluations)"
mkdir -p "$RUNTIME"
python3 - "$RUNTIME" <<'EOF'
import sys, wave
for track in ("mixed", "caller", "agent"):
    with wave.open(f"{sys.argv[1]}/{track}.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(bytes((i * 7 + len(track)) % 256 for i in range(16000 * 2 * 2)))  # 2 s
EOF
ls -l "$RUNTIME"
seed() { "${DC[@]}" run --rm -T -v "$PWD/$OUT:/proof:ro" api python /proof/seed_results.py "$@" 2>&1 | grep -v Container; }
seed "$RUN_A" 86:pass 95:pass 40:fail 70:fail 60:fail 90:pass
seed "$RUN_B" 52:fail 85:pass 72.5:fail 70:fail - 91:pass

section "GET /calls (Audits list) vs the calls table"
call "$API/calls?limit=3" | pj "[{k: c[k] for k in ('id','source','status','run_id','overall_score','passed','critical_failure','needs_human_review','human_reviewed')} for c in d['items']]"
echo "next_cursor set: $(call "$API/calls?limit=3" | python3 -c "import sys,json; print(bool(json.load(sys.stdin)['next_cursor']))")"
sql "SELECT c.id, c.source, c.status, r.run_id, e.overall_score, e.passed, e.critical_failure, e.needs_human_review FROM calls c JOIN run_items r ON r.id = c.run_item_id JOIN evaluations e ON e.call_id = c.id ORDER BY c.started_at DESC, c.id DESC LIMIT 3"
echo "-- filters: source=simulation / run_id / needs_review=true&reviewed=false / status"
for q in "source=simulation&limit=200" "run_id=$RUN_A&limit=200" "needs_review=true&reviewed=false&limit=200" "status=error&limit=200"; do
  printf '%-52s -> %s calls\n' "$q" "$(call "$API/calls?$q" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['items']))")"
done
sql "SELECT count(*) FILTER (WHERE true) AS all_calls, count(*) FILTER (WHERE e.needs_human_review) AS needs_review FROM calls c JOIN evaluations e ON e.call_id = c.id"

section "GET /calls/{id} for the 40-point call of the base run vs its rows"
CALL=$(sqlv "SELECT c.id FROM calls c JOIN run_items r ON r.id = c.run_item_id JOIN evaluations e ON e.call_id = c.id WHERE r.run_id = '$RUN_A' AND e.overall_score = 40")
echo "CALL=$CALL"
call "$API/calls/$CALL" | pj
sql "SELECT idx, speaker, text, ground_truth_text, agent_heard_text, is_barge_in FROM turns WHERE call_id = '$CALL' ORDER BY idx"
sql "SELECT seq, name, arguments, at_ms FROM tool_calls WHERE call_id = '$CALL'"
sql "SELECT check_type, check_key, passed, evidence_turns FROM deterministic_checks WHERE call_id = '$CALL' ORDER BY 1"
sql "SELECT overall_score, passed, critical_failure, needs_human_review, review_reasons, failure_types FROM evaluations WHERE call_id = '$CALL'"

section "GET /calls/{id}/audio/{track}: full file, Range, 416, errors"
curl -s -D - -o /tmp/api04_full.wav -H "Authorization: Bearer $KEY" "$API/calls/$CALL/audio/mixed" | grep -iE "^HTTP|content-type|content-length|accept-ranges"
echo "downloaded sha256: $(sha256sum /tmp/api04_full.wav | cut -c1-16)  file on disk: $(sha256sum $RUNTIME/mixed.wav | cut -c1-16)"
curl -s -D - -o /tmp/api04_part.bin -H "Authorization: Bearer $KEY" -H "Range: bytes=100-199" "$API/calls/$CALL/audio/mixed" | grep -iE "^HTTP|content-range|content-length"
echo "range bytes equal to file[100:200]: $(python3 -c "print(open('/tmp/api04_part.bin','rb').read() == open('$RUNTIME/mixed.wav','rb').read()[100:200])")"
curl -s -D - -o /dev/null -H "Authorization: Bearer $KEY" -H "Range: bytes=-16" "$API/calls/$CALL/audio/mixed" | grep -iE "^HTTP|content-range"
SIZE=$(stat -c %s "$RUNTIME/mixed.wav")
call -H "Range: bytes=$SIZE-" -w '\nHTTP %{http_code}\n' "$API/calls/$CALL/audio/mixed"
call -w '\nHTTP %{http_code} (original track not recorded)\n' "$API/calls/$CALL/audio/original"

section "GET /runs/compare?base=A&head=B vs the evaluations of both runs"
call "$API/runs/compare?base=$RUN_A&head=$RUN_B" | pj
sql "SELECT left(s.title, 30) AS scenario, n.name AS profile, max(e.overall_score) FILTER (WHERE r.run_id = '$RUN_A') AS base, max(e.overall_score) FILTER (WHERE r.run_id = '$RUN_B') AS head FROM run_items r JOIN scenarios s ON s.id = r.scenario_id JOIN noise_profiles n ON n.id = r.noise_profile_id LEFT JOIN calls c ON c.run_item_id = r.id LEFT JOIN evaluations e ON e.call_id = c.id WHERE r.run_id IN ('$RUN_A','$RUN_B') GROUP BY 1, 2 ORDER BY 1, 2"
call -w 'unknown head -> HTTP %{http_code}\n' -o /dev/null "$API/runs/compare?base=$RUN_A&head=00000000-0000-0000-0000-000000000000"

section "GET /runs/{id}/report (HTML)"
curl -s -D - -o /tmp/api04_report.html -H "Authorization: Bearer $KEY" "$API/runs/$RUN_A/report" | grep -iE "^HTTP|content-type"
wc -c /tmp/api04_report.html
grep -oE "<title>[^<]*</title>|<dt>[^<]*</dt><dd>[^<]*</dd>" /tmp/api04_report.html | head -12
grep -c "<tr><td>" /tmp/api04_report.html | sed 's/^/matrix rows in the report: /'

section "GET /usage and GET /metrics/summary vs api_usage (rows seeded: two providers)"
sql "INSERT INTO api_usage (provider, operation, units, unit_type, est_cost) VALUES ('gnani','tts',1200,'characters',4.2),('gnani','tts',800,'characters',2.8),('gnani','stt_batch',95.5,'audio_seconds',3.1),('deepseek','llm_judge',42000,'tokens',1.9)"
call "$API/usage" | pj
sql "SELECT provider, operation, unit_type, sum(units) AS units, sum(est_cost) AS est_cost FROM api_usage GROUP BY 1,2,3 ORDER BY 1,2,3"
call "$API/metrics/summary" | pj

section "SSE: run C created while the planner is stopped (its run.requested waits on the bus)"
"${DC[@]}" stop planner 2>&1 | tail -1
RUN_C=$(new_run "API-04 live"); echo "RUN_C=$RUN_C"
sleep 3
echo "-- GET /metrics/summary: planner group lag"
call "$API/metrics/summary" | pj "d['consumer_lag']"
"${DC[@]}" exec -T kafka $KAFKA_BIN/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group planner 2>&1 | grep -E "GROUP|run.requested" | sort -u

section "SSE #1: connect (snapshot only: nothing planned yet), then drop"
curl -sN --max-time 4 -H "Authorization: Bearer $KEY" "$API/runs/$RUN_C/events" > /tmp/api04_sse1.txt || true
python3 - <<'EOF'
chunks = [c for c in open("/tmp/api04_sse1.txt").read().split("\n\n") if c]
for c in chunks:
    head, _, data = c.partition("\ndata: ")
    print(head.replace("\n", " | "), "| data:", data[:230], "...")
EOF
LAST_ID=$(grep '^id: ' /tmp/api04_sse1.txt | tail -1 | cut -c5-)
echo "Last-Event-ID to resume with: $LAST_ID"

section "planner restarts while no client is connected: 6 item.status events are produced"
"${DC[@]}" start planner 2>&1 | tail -1
wait_for 60 items_planned "$RUN_C" 6
sleep 2
sql "SELECT status, count(*) FROM run_items WHERE run_id = '$RUN_C' GROUP BY 1"

section "SSE #2: reconnect with Last-Event-ID: fresh snapshot, then the 6 events it missed"
curl -sN --max-time 6 -H "Authorization: Bearer $KEY" -H "Last-Event-ID: $LAST_ID" "$API/runs/$RUN_C/events" > /tmp/api04_sse2.txt || true
python3 - <<'EOF'
import json
chunks = [c for c in open("/tmp/api04_sse2.txt").read().split("\n\n") if c]
for c in chunks:
    lines = dict(l.split(": ", 1) for l in c.strip().split("\n"))
    data = json.loads(lines["data"])
    if lines["event"] == "snapshot":
        print(f"id={lines['id']} event=snapshot progress={data['run']['progress']} items={len(data['items'])}")
    else:
        print(f"id={lines['id']} event={lines['event']} {{status: {data['status']}, scenario: {str(data['scenario'])[:24]}}}")
print(len(chunks) - 1, "events after the snapshot")
EOF

section "SSE #3: live stream; POST /runs/{id}/cancel makes the API emit item.status x6 + run.completed, then the stream ends"
curl -sN --max-time 40 -H "Authorization: Bearer $KEY" "$API/runs/$RUN_C/events" > /tmp/api04_sse3.txt &
SSE_PID=$!
sleep 3
call -X POST "$API/runs/$RUN_C/cancel" | pj "{'status': d['status'], 'progress': d['progress']}"
wait $SSE_PID || true
python3 - <<'EOF'
import json
chunks = [c for c in open("/tmp/api04_sse3.txt").read().split("\n\n") if c]
for c in chunks:
    lines = dict(l.split(": ", 1) for l in c.strip().split("\n"))
    data = json.loads(lines["data"])
    shown = {"snapshot": lambda d: f"run.status={d['run']['status']} progress={d['run']['progress']}"}.get(lines["event"], lambda d: json.dumps(d)[:150])(data)
    print(f"event={lines['event']:<13} {shown}")
print("stream closed by the server after run.completed:", chunks[-1].split("\n")[1] == "event: run.completed")
EOF

section "SSE on a finished run, unknown run, no key"
curl -sN --max-time 10 -H "Authorization: Bearer $KEY" "$API/runs/$RUN_A/events" | python3 -c "
import sys
for c in sys.stdin.read().split('\n\n'):
    if c: print(c.split('\n')[1], '|', c.split('\n')[2][:110])"
call -o /dev/null -w 'unknown run -> HTTP %{http_code}\n' "$API/runs/00000000-0000-0000-0000-000000000000/events"
curl -s -o /dev/null -w 'no key -> HTTP %{http_code}\n' "$API/runs/$RUN_A/events"

section "outbox backlog: stop the relay, create a run, read /metrics/summary, restart the relay"
"${DC[@]}" stop outbox-relay 2>&1 | tail -1
RUN_D=$(new_run "API-04 backlog"); echo "RUN_D=$RUN_D"
call "$API/metrics/summary" | pj "{'outbox_backlog': d['outbox_backlog']}"
sql "SELECT count(*) AS unpublished_outbox_rows FROM outbox_events WHERE published_at IS NULL"
"${DC[@]}" start outbox-relay 2>&1 | tail -1
wait_eval 30 '[ "$(sqlv "SELECT count(*) FROM outbox_events WHERE published_at IS NULL")" = 0 ]'
call "$API/metrics/summary" | pj "{'outbox_backlog': d['outbox_backlog'], 'consumer_lag': d['consumer_lag']}"
call -X POST "$API/runs/$RUN_D/cancel" -o /dev/null

section "DLQ: an unhandleable run.requested goes bus -> planner -> dlq -> dlq-recorder -> dead_letters"
"${DC[@]}" run --rm -T -v "$PWD/$OUT:/proof:ro" api python /proof/dlq_demo.py 2>&1 | grep -v Container
wait_eval 60 '[ "$(open_dl_count)" -ge 1 ]'
call "$API/dlq?limit=5" | pj "[{k: (x[k] if k != 'envelope' else {'type': x[k]['type'], 'attempt': x[k]['attempt']}) for k in x} for x in d['items']]"
sql "SELECT id, event_id, original_topic, consumer_group, status, attempts, left(error, 60) AS error FROM dead_letters ORDER BY failed_at DESC"
DL=$(sqlv "SELECT id FROM dead_letters WHERE status = 'open' ORDER BY failed_at DESC LIMIT 1")
call "$API/metrics/summary" | pj "{'dlq_open': d['dlq_open']}"
echo "-- replay $DL (admin): new outbox row, same event_id, attempt 1"
call -X POST "$API/dlq/$DL/replay" | pj "{'http': 202, 'id': d['id'], 'status': d['status'], 'attempts': d['attempts']}"
sql "SELECT status, replayed_at IS NOT NULL AS has_replayed_at FROM dead_letters WHERE id = '$DL'"
echo "-- the planner fails it again; the recorder re-opens the same row"
wait_eval 60 '[ "$(dl_status)" = open ]'
sql "SELECT id, status, attempts, replayed_at FROM dead_letters WHERE id = '$DL'"
call -X POST "$API/dlq/$DL/replay" -o /dev/null -w 'replay again while open -> HTTP %{http_code} (open again after the failed retry)\n'
wait_eval 60 '[ "$(dl_status)" = open ]'
call -X POST "$API/dlq/$DL/discard" | pj "{'id': d['id'], 'status': d['status']}"
call -X POST "$API/dlq/$DL/discard" -o /dev/null -w 'discard twice -> HTTP %{http_code}\n'
call "$API/dlq?status=discarded" | pj "[(x['id'][:8], x['status']) for x in d['items']]"
call "$API/metrics/summary" | pj "{'dlq_open': d['dlq_open']}"
sql "SELECT status, count(*) FROM dead_letters GROUP BY 1 ORDER BY 1"

echo
echo "commit: $(git rev-parse --short HEAD)"
