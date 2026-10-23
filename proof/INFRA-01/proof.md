# INFRA-01 proof

## Built
- `docker-compose.yml` (from `docs/starter/`): Kafka 4.0.0 KRaft (single node, healthcheck), `kafka-init` (idempotent topics), Postgres 16, `migrate`, `api`, `web`, `mock-agent`, optional `kafka-ui` (profile `tools`).
- Worker services (outbox-relay, planner, simulator, ...) are kept but behind compose profile `workers`: their modules do not exist until INFRA-02 and later, so they would crash-loop. Enable with `docker compose --profile workers up -d` once they exist.
- `infra/kafka/create-topics.sh`: copied unchanged from the starter (12 topics, matches the TL contract list in docs).
- Placeholders (all marked `STUB(INFRA-01)`): `backend/pareeksha/api/main.py` (only `GET /health`, a real DB + Kafka metadata check), `mock_agent/server.py` (`/health`), `web/` (nginx static page on :3000). `migrate` runs `alembic upgrade head` once `backend/alembic.ini` exists (API-01), otherwise prints a no-op message.
- `.env.example` (pre-existing, unchanged); compose does not require a `.env` (`env_file ... required: false`). The captured run had no `.env`.
- `docker-compose.proxy.yml`: optional overlay that passes a CA bundle as a build secret; needed only behind a TLS-intercepting proxy (this sandbox). Not needed on a normal machine.
- Image tags verified by real pull on 2026-10-23: `apache/kafka:4.0.0`, `postgres:16`, `python:3.12-slim`, `nginx:1.27-alpine`, `ghcr.io/kafbat/kafka-ui:latest`.

## Reproduce
```
cp .env.example .env
docker compose up -d --build            # sandbox behind proxy: CA_BUNDLE=/root/.ccr/ca-bundle.crt docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d --build
./proof/INFRA-01/capture.sh             # sandbox: COMPOSE_EXTRA="-f docker-compose.yml -f docker-compose.proxy.yml"
```

## Expected (real output in `health.txt`)
- kafka, postgres, api, mock-agent `healthy`; kafka-init and migrate `Exited (0)`; web up on :3000.
- `GET :8000/health` -> `200 {"db":"ok","kafka":"ok"}`.
- 12 `pareeksha.*` topics with the partition/retention values from `create-topics.sh`; re-running kafka-init exits 0 and creates nothing new.
- Host listener `localhost:9094` answers broker API versions.

## Not covered
- Worker containers (INFRA-02+), real api/migrate (API-01), Next.js web (FE-01), mock agent (VOICE-03).
- `kafka-ui` profile not started.

## Tracked stubs (owner replaces; none are INFRA-01s)
| File | Marker | Replaced by |
|---|---|---|
| backend/pareeksha/api/main.py | STUB(TL-01) | TL-01 real FastAPI app. It must keep GET /health (no auth) with db + kafka checks: {"db":"ok","kafka":"ok"}, 503 when either is down. The compose api healthcheck and web depends_on rely on it. |
| mock_agent/server.py | STUB(VOICE-03) | Mock EMI agent (pareeksha-audio-v1); keep /health on :8765 |
| web/Dockerfile + web/index.html | STUB(FE-01) | Next.js app on :3000 |
| backend/alembic_migrate.sh | STUB(API-01) | alembic upgrade head once alembic.ini exists |
