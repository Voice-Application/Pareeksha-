#!/usr/bin/env bash
# Exercises gen:api against the fixture: up-to-date passes, tampered file is reported stale, missing backend fails loudly.
set -u
cd "$(dirname "$0")/.."
SRC=tests/fixtures/openapi.health.json
node scripts/gen-api.mjs --from "$SRC"
node scripts/gen-api.mjs --check --from "$SRC"; echo "fresh exit=$?"
echo '// tampered' >> lib/api/schema.d.ts
node scripts/gen-api.mjs --check --from "$SRC"; echo "stale exit=$?"
node scripts/gen-api.mjs --from "$SRC"
node scripts/gen-api.mjs --check --from "$SRC"; echo "regenerated exit=$?"
node scripts/gen-api.mjs --check --from http://127.0.0.1:9/openapi.json; echo "unreachable exit=$?"
