# M2b integration proof

Branch `integrate/M2b`. Merged: INT-01b, EVAL-03b, API-03, VOICE-03, EVAL-04.

## Reconciliation
- `workers/evaluator.py` + `evaluation/pg_stores.py` (EVAL-03b) are the only evaluator. EVAL-04's duplicate `evaluator/evaluation/store.py` is gone; `workers/auditor.py` and `audit/*` hand the `call.completed` they emit to this evaluator (tests: `tests/integration/test_audit_*.py`, `test_agent_role_swap.py`).
- One `events/outbox.enqueue_session`. Both reconcilers kept: `workers/reconciler.py` (API-03 run slots, compose service `reconciler`) and `evaluation/completion_reconciler.py` (EVAL-03b, run inside the `finalizer` process).
- Dependencies unioned: `backend/Dockerfile` + `pyproject.toml` gained `websockets`, `google-auth`, `audioop-lts` (py>=3.13). `docker-compose.proxy.yml` now covers `mock-agent`. Compose carries every worker service.
- Test-isolation fixes: budget tests (spend is account-wide) clear `api_usage` first; the health-503 test pins unreachable DB/Kafka itself instead of relying on an empty environment.

## Results (private stack: `pk-m2b` compose project, Postgres :15432, Kafka :19094)
- Env: `DATABASE_URL`, `TEST_DATABASE_URL`, `INFRA_TEST_DATABASE_URL` (port 15432), `KAFKA_BOOTSTRAP_SERVERS`, `INFRA_TEST_KAFKA_BOOTSTRAP=localhost:19094`.
- `cd backend && python3 -m pytest -q`: 1024 passed in the last full run (`pytest_full.txt`); the one remaining failure there (`test_health_reports_down_dependencies_with_503`, env-dependent) was fixed afterwards and re-run: `tests/contract/test_stub_routes.py` 147 passed. Total 1025 collected, 0 skipped.
- `ruff check .` clean; `ruff format --check .` 240 files formatted; `python3 -m mypy` no issues in 244 files.
- `sdk/python`: 50 passed.
- `web`: `npm run lint`, `npm run typecheck`, `npm run build` all pass.
- `BUILDX_BAKE_ENTITLEMENTS_FS=0 CA_BUNDLE=/root/.ccr/ca-bundle.crt docker compose -f docker-compose.yml -f docker-compose.proxy.yml build api mock-agent`: both built.

STATUS: done-unverified (see commit SHA in report).
