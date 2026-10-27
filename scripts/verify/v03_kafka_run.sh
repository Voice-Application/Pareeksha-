#!/usr/bin/env bash
# V3 (NFR-1, NFR-3, NFR-4c): 20 calls at concurrency 4 in < 15 min, then the 5x4x2 = 40-call run through Kafka with
# >= 95% of items free of infra errors, consumer lag 0 at the end and the DLQ count recorded.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 3 "40-call Kafka run, >= 95% free of infra errors; 20-call concurrency-4 timing"
"$ROOT/scripts/verify/step3_perf_20call.sh"; perf=$?
"$ROOT/scripts/verify/step3_kafka_40call.sh"; kafka=$?
# the two sub-steps append their own sections to V3.md
[ $perf -eq 0 ] && [ $kafka -eq 0 ] && finish PASS "20-call timing and 40-call run both met their criteria"
finish FAIL "20-call timing exit $perf, 40-call run exit $kafka"
