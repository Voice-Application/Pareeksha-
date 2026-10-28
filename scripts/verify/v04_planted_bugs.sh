#!/usr/bin/env bash
# V4: >= 4 of 5 planted mock-agent bugs caught with cited turn indices that exist in the transcript.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 4 ">= 4 of 5 planted bugs caught with cited turn indices"
$PY scripts/verify/v04_planted_bugs.py 2>&1 | tee "$OUT/V4.log" | block
rc=${PIPESTATUS[0]}
note "Machine-readable: proof/verify/V4.catch_report.json"
[ "$rc" -eq 0 ] && finish PASS "$(grep -E "caught [0-9]/5" "$OUT/V4.log" | tail -1)"
finish FAIL "$(grep -E "caught [0-9]/5" "$OUT/V4.log" | tail -1)"
