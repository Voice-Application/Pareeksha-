#!/usr/bin/env bash
# Verifies the optional WEB_PASSWORD gate against a production build (run `npm run build` first).
set -u
cd "$(dirname "$0")/.."
WEB_PASSWORD=s3cret PAREEKSHA_API_URL=http://127.0.0.1:9/api/v1 npx next start -p 3101 -H 127.0.0.1 >/dev/null 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT
for _ in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:3101/ && break; sleep 0.5; done
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
echo "no credentials  / -> $(code http://127.0.0.1:3101/)"
echo "no credentials  /api/proxy/api/v1/health -> $(code http://127.0.0.1:3101/api/proxy/api/v1/health)"
echo "wrong password  / -> $(code -u u:wrong http://127.0.0.1:3101/)"
echo "right password  / -> $(code -u u:s3cret http://127.0.0.1:3101/)"
echo "right password  /api/proxy/api/v1/health (upstream down) -> $(code -u u:s3cret http://127.0.0.1:3101/api/proxy/api/v1/health)"
