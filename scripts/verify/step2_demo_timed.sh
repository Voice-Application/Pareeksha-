#!/usr/bin/env bash
# V2 (FR-DX-1, NFR-11, NFR-14): clock starts, compose up, wait healthy, make demo, an evaluation row with a score
# exists, elapsed < 1200 s. Run on a fresh clone with only GNANI_API_KEY and DEEPSEEK_API_KEY in .env.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 2 "compose up + make demo gives an evaluated call in < 20 min"
start=$(date +%s)
echo "[$(date -u +%T)] make demo (compose up --build, health wait, seed, 10-call demo run)" > "$OUT/V2.demo.log"
make demo >> "$OUT/V2.demo.log" 2>&1
rc=$?
echo "[$(date -u +%T)] demo returned $rc" >> "$OUT/V2.demo.log"
tail -25 "$OUT/V2.demo.log" | block
elapsed=$(( $(date +%s) - start ))
scored=$(psql_q "SELECT count(*) FROM evaluations WHERE overall_score IS NOT NULL" 2>/dev/null || echo 0)
unhealthy=$($COMPOSE ps --format '{{.Service}} {{.Health}}' 2>/dev/null | grep -c unhealthy || true)
note "Elapsed: ${elapsed}s (limit 1200s). Evaluations with a score: ${scored}. Unhealthy services: ${unhealthy}. Full log: proof/verify/V2.demo.log"
[ "$rc" -eq 0 ] || finish FAIL "make demo exited non-zero"
[ "${scored:-0}" -ge 1 ] || finish FAIL "no scored evaluation in Postgres"
[ "$elapsed" -lt 1200 ] || finish FAIL "took ${elapsed}s, limit 1200s"
finish PASS "evaluated call in ${elapsed}s (${scored} scored evaluations)"
