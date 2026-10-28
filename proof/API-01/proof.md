# API-01 proof

## Built
- `backend/alembic.ini`, `backend/alembic/env.py`: Alembic reading `DATABASE_URL` (sync psycopg 3). `versions/0001_initial.py` executes `backend/alembic/sql/0001_initial.sql`, a byte-for-byte copy of `docs/schema.sql` v0.2 (a test enforces the copy), so partial indexes, CHECKs and the `pgcrypto` extension are exactly as documented. Downgrade drops all 29 tables.
- `backend/alembic_migrate.sh`: STUB(API-01) removed; now `exec alembic upgrade head` (idempotent). The compose `migrate` service uses it unchanged.
- `backend/pareeksha/db/models.py`: SQLAlchemy 2.0 models for all 29 tables, generated with sqlacodegen from a database built from `schema.sql` (one fix by hand: `CallMetrics` is a plain `Base` model, sqlacodegen had made it a joined subclass of `Calls`).
- `backend/pareeksha/db/session.py`: async engine/sessionmaker (psycopg 3), lazy `DATABASE_URL`; `get_session` dependency (commit on success, rollback on error); `get_session_factory` dependency (overridable).
- `backend/pareeksha/api/auth.py`: STUB(API-01) removed. SHA-256 lookup in `api_keys` (not revoked) -> 401 `unauthorized` for missing/unknown/revoked; 403 `forbidden` (details: required/granted) when the key lacks the route scope; `admin` implies all; `last_used_at` updated only on accepted requests; returns `Principal(key_id, project_id, scopes)`. `generate_api_key()` yields `pk_live_<256-bit token>`, 16-char display prefix and hash (the full key exists only in the caller that creates it: API-02 `POST /api-keys` returns it once).
- `backend/pyproject.toml`: added `sqlalchemy[asyncio]`, `alembic` (runtime), `gnani-vachana>=0.8.2` (dev); ruff isort/per-file ignore for generated models; coverage `concurrency = ["thread","greenlet"]` (needed to measure async SQLAlchemy code).
- `backend/tests/contract/test_stub_routes.py`: overrides `authenticate` with a header-only fake (those tests check 501/401 envelopes, not key lookup).

## Reproduce
```
cp .env.example .env
# sandbox behind TLS proxy: export CA_BUNDLE=/root/.ccr/ca-bundle.crt BUILDX_BAKE_ENTITLEMENTS_FS=0
COMPOSE_EXTRA="-f docker-compose.yml -f docker-compose.proxy.yml" ./proof/API-01/capture.sh   # normal machine: ./proof/API-01/capture.sh
cd backend && pip install -e ".[dev]" && docker compose up -d postgres   # (from repo root)
python -m pytest -q --cov=pareeksha        # tests/db create and drop pareeksha_test_<hex> on the compose Postgres
ruff check . && ruff format --check . && python -m mypy
```
Note: `python -m pytest` rather than bare `pytest` if several pytest installs exist on PATH.

## Results (real output)
- `migrate_and_tables.txt`: compose `migrate` service on an empty Postgres 16: `Running upgrade -> 0001`, exit 0; re-run exit 0; `\dt` shows 29 tables + `alembic_version` (`0001`); `\d api_keys`; the three partial indexes.
- `pytest.txt`: 560 passed, 0 failed, 0 skipped; total coverage 98% (new code: auth.py, db/session.py, models and migration exercised against real Postgres, no mocks).
- ruff check, ruff format --check, mypy strict: clean.
- DB tests cover: tables/columns/indexes of the migrated DB equal `schema.sql` and the models; downgrade -> upgrade round trip; `alembic_migrate.sh` idempotent; 401 missing/unknown/revoked; 403 insufficient scope; admin implies all; `last_used_at`; only hash stored; session commit/rollback.

## Not covered / notes
- Key creation/listing/revocation endpoints and seeding a demo key are API-02 (routes still return 501 after passing auth).
- The compose `api` service Dockerfile still installs the minimal pip list from INFRA-01 (it already includes sqlalchemy, alembic, psycopg); `greenlet` comes in transitively with SQLAlchemy.
- `.env` copied from `.env.example` for the compose run is git-ignored and not committed.
