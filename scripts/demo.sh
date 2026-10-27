#!/usr/bin/env bash
# `make demo`: make .env usable, start the stack, seed, register the mock agent and run a 10-call demo.
#   COMPOSE="docker compose -f docker-compose.yml -f docker-compose.proxy.yml"   # behind a TLS-intercepting proxy
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=${COMPOSE:-docker compose}
export COMPOSE

[ -f .env ] || cp .env.example .env

# Set KEY=value in .env only when KEY is empty or missing (never overwrites a value you chose).
ensure() {
  local key=$1 value=$2
  if grep -Eq "^${key}=.+" .env; then return; fi
  if grep -Eq "^${key}=" .env; then
    sed -i.bak -E "s|^${key}=.*|${key}=${value}|" .env && rm -f .env.bak
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
  echo "generated ${key} in .env"
}
ensure SECRET_KEY "$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
ensure PAREEKSHA_API_KEY "pk_live_$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
ensure SIMULATOR_REPLICAS 1
for var in GNANI_API_KEY DEEPSEEK_API_KEY; do
  grep -Eq "^${var}=.+" .env || { echo "ERROR: ${var} is empty in .env; set it and re-run" >&2; exit 1; }
done

$COMPOSE --profile workers up -d --build
port=$(grep -E '^API_HOST_PORT=' .env | cut -d= -f2 | cut -d' ' -f1 || true)
port=${port:-8000}
echo "waiting for the API on :${port} ..."
for _ in $(seq 1 120); do
  curl -fsS "http://localhost:${port}/health" >/dev/null 2>&1 && break
  sleep 5
done
curl -fsS "http://localhost:${port}/health" >/dev/null

$COMPOSE run --rm api python -m pareeksha.seed
python3 scripts/verify/vapi.py demo
echo "Demo done. Web app: http://localhost:$(grep -E '^WEB_HOST_PORT=' .env | cut -d= -f2 | cut -d' ' -f1 || echo 3000)  (API key is PAREEKSHA_API_KEY in .env)"
