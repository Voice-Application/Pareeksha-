#!/usr/bin/env bash
# Reproduces proof/API-02: migrate a scratch database on the compose Postgres, run the seed twice,
# start the real API (uvicorn) on it and exercise the CRUD routes with curl, including a LIVE
# persona preview against Gnani Timbre TTS (needs GNANI_API_KEY in the environment or .env).
# Usage (repo root, Postgres up: `docker compose up -d postgres`): ./proof/API-02/capture.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=proof/API-02
PG_HOST=${PG_HOST:-localhost}
PG_PORT=${PG_PORT:-5432}
export PGPASSWORD=${PGPASSWORD:-pareeksha}
if [ -f .env ]; then set -a; . ./.env; set +a; fi
DB="pareeksha_api02_$$"
PORT=${API_PORT:-8100}
psql -h "$PG_HOST" -p "$PG_PORT" -U pareeksha -d postgres -qc "CREATE DATABASE $DB"
cleanup() {
  [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
  psql -h "$PG_HOST" -p "$PG_PORT" -U pareeksha -d postgres -qc "DROP DATABASE IF EXISTS $DB WITH (FORCE)" || true
}
trap cleanup EXIT
export DATABASE_URL="postgresql+psycopg://pareeksha:pareeksha@$PG_HOST:$PG_PORT/$DB"
export SECRET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
# A throwaway key that only ever exists in this scratch database (pinned so the output is stable).
export PAREEKSHA_API_KEY="pk_live_proof-api02-throwaway-key-0001"
export DATA_DIR="$PWD/$OUT/runtime"
mkdir -p "$DATA_DIR"
cd backend
alembic upgrade head 2>&1 | tail -2
python -m pareeksha.seed | tee "../$OUT/seed_run1.txt"
python -m pareeksha.seed | tee "../$OUT/seed_run2.txt"
uvicorn pareeksha.api.main:app --port "$PORT" --log-level warning &
API_PID=$!
cd ..
for _ in $(seq 1 40); do curl -s "localhost:$PORT/openapi.json" -o /dev/null && break; sleep 0.5; done
A="Authorization: Bearer $PAREEKSHA_API_KEY"
B="localhost:$PORT/api/v1"
{
  echo "# counts via the API (demo key)"
  echo "personas:       $(curl -s -H "$A" "$B/personas?limit=200" | python -c 'import sys,json; print(len(json.load(sys.stdin)["items"]))')"
  echo "noise profiles: $(curl -s -H "$A" "$B/noise-profiles" | python -c 'import sys,json; print(len(json.load(sys.stdin)["items"]))')"
  echo "agents:         $(curl -s -H "$A" "$B/agents" | python -c 'import sys,json; print([a["name"] for a in json.load(sys.stdin)["items"]])')"
  echo "scenarios:      $(curl -s -H "$A" "$B/scenarios?limit=200" | python -c 'import sys,json; print(len(json.load(sys.stdin)["items"]))')"
  echo
  echo "# no key -> 401; garbage key -> 401"
  curl -s -o /dev/null -w "%{http_code}\n" "$B/agents"
  curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer pk_live_nope" "$B/agents"
  echo
  echo "# create a read-only key, use it, fail a write with it, revoke it"
  NEW=$(curl -s -X POST -H "$A" -H 'content-type: application/json' -d '{"name":"ci","scopes":["read"]}' "$B/api-keys")
  echo "$NEW" | python -c 'import sys,json; d=json.load(sys.stdin); d["key"]=d["key"][:12]+"…(shown once)"; print(json.dumps(d))'
  KEY=$(echo "$NEW" | python -c 'import sys,json; print(json.load(sys.stdin)["key"])')
  KID=$(echo "$NEW" | python -c 'import sys,json; print(json.load(sys.stdin)["id"])')
  curl -s -o /dev/null -w "GET agents with new key: %{http_code}\n" -H "Authorization: Bearer $KEY" "$B/agents"
  curl -s -w "\nPOST agents with read key: %{http_code}\n" -X POST -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"name":"x","endpoint_url":"ws://x"}' "$B/agents"
  curl -s -o /dev/null -w "DELETE key: %{http_code}\n" -X DELETE -H "$A" "$B/api-keys/$KID"
  curl -s -o /dev/null -w "GET agents with revoked key: %{http_code}\n" -H "Authorization: Bearer $KEY" "$B/agents"
  echo
  echo "# list keys (prefix, scopes, last_used_at; never the key)"
  curl -s -H "$A" "$B/api-keys" | python -m json.tool
  echo
  echo "# integrations: webhook shows the signing secret once; secrets_set afterwards; ciphertext in DB"
  WH=$(curl -s -X POST -H "$A" -H 'content-type: application/json' -d '{"connector":"webhook","name":"ci hook","config":{"url":"https://ci.example.com/hook"}}' "$B/integrations")
  echo "$WH" | python -c 'import sys,json; d=json.load(sys.stdin); d["signing_secret"]="<"+str(len(d["signing_secret"]))+" chars, shown once>"; print(json.dumps(d,indent=2))'
  WID=$(echo "$WH" | python -c 'import sys,json; print(json.load(sys.stdin)["id"])')
  curl -s -H "$A" "$B/integrations/$WID" | python -m json.tool
  psql -h "$PG_HOST" -p "$PG_PORT" -U pareeksha -d "$DB" -Atc "select connector, left(encode(secrets_encrypted,'escape'),20) || '…' as ciphertext_prefix from integrations"
} 2>&1 | tee "$OUT/api_walkthrough.txt"
# Noise preview (built-in sample through pstn_market_5db) and a LIVE Gnani persona preview.
NP=$(curl -s -H "$A" "$B/noise-profiles" | python -c 'import sys,json; print([p["id"] for p in json.load(sys.stdin)["items"] if p["name"]=="pstn_market_5db"][0])')
curl -s -X POST -H "$A" "$B/noise-profiles/$NP/preview" -o "$OUT/noise_preview_pstn_market_5db.wav" -w "noise preview: %{http_code} %{content_type} %{size_download} bytes\n" | tee "$OUT/previews.txt"
PE=$(curl -s -H "$A" "$B/personas?limit=200&language=kn-IN" | python -c 'import sys,json; print([p["id"] for p in json.load(sys.stdin)["items"] if p["name"].startswith("Manju")][0])')
curl -s -X POST -H "$A" "$B/personas/$PE/preview" -o "$OUT/persona_preview_manju_kn.wav" -w "persona preview (live Gnani): %{http_code} %{content_type} %{size_download} bytes\n" | tee -a "$OUT/previews.txt"
python - <<'PY' | tee -a "$OUT/previews.txt"
import wave
for f in ("noise_preview_pstn_market_5db.wav", "persona_preview_manju_kn.wav"):
    try:
        with wave.open(f"proof/API-02/{f}") as w:
            print(f, w.getframerate(), "Hz", round(w.getnframes() / w.getframerate(), 2), "s")
    except Exception as exc:
        print(f, "not a readable WAV:", exc)
PY
curl -s "localhost:$PORT/openapi.json" | python -c '
import sys, json
spec = json.load(sys.stdin)
ops = [(m, p) for p, item in spec["paths"].items() for m in item]
print("operations in OpenAPI:", len(ops))' | tee -a "$OUT/previews.txt"
rm -rf "$OUT/runtime"
