# M3 integration proof

Branch `integrate/M3`, from `task/VOICE-05` (00a47b1). Merged in order: API-04, API-05, EVAL-05, QA-02, INT-03, VOICE-06, FE-03, FE-04, FE-05 (FE-03/04 were inside FE-05).

## Conflicts and integration fixes
- `api/routers/calls.py` (API-04 read endpoints vs INT/VOICE `POST /calls` + speaker-map + API-05 review/promote/reevaluate): imports unioned, handlers kept as merged; `not_implemented` import dropped (no stub routes remain).
- `tests/integration/conftest.py` (blobs/rubric/private_api fixtures vs `data_dir`/`pg`): all fixtures kept.
- `backend/Dockerfile`: `pip install --no-deps /app` after COPY so the `pareeksha.connectors` entry points (webhook, hubspot) exist in the image; `rapidfuzz` was already in the dep line. Check (`image_check.txt`): `rapidfuzz ok ['hubspot', 'webhook']` inside `pk-m3-api`.
- `web/Dockerfile` + `docker-compose.proxy.yml`: optional CA build secret for `npm ci` behind a TLS-intercepting proxy (sandbox only).
- `tests/contract/test_stub_routes.py`: no stub routes remain, so the two stub-only parametrized tests (which skip on an empty set) became one `test_every_route_is_implemented`; owner-board test no longer asserts a non-empty stub set. This is what gives 0 skipped.
- `web/lib/api/schema.d.ts` regenerated with `openapi-typescript` from the live `/openapi.json` of the built stack (`typecheck`/`lint` pass on it).

## Results (private stack `pk-m3`: Postgres :25432, Kafka :29094)
- Backend `python3 -m pytest` (`pytest_full.txt`, run on the `task/QA-03` tree = integrate/M3 + QA-03 fixes): **1237 passed, 1 failed, 0 skipped**. The failure is `tests/kafka/test_kafka_down_outbox.py::test_api_accepts_while_kafka_is_down_and_the_outbox_drains_in_per_key_order`: all assertions pass (health 503 while down, writes accepted, backlog 12 kept, outbox drains to 0) and then the relay's `producer.stop()` never returns (hang in aiokafka `MessageAccumulator.close`, 30 s and also 90 s timeout). It passed twice in isolation early in the session (22 s; `tests/kafka` 9/9) and fails on every later run, in the full suite and alone, so it is flaky-to-failing in this stack, not an order effect. Not root-caused (QA-02 owner).
- `ruff check .` clean; `ruff format --check .` clean; `python3 -m mypy`: no issues in 336 files.
- `sdk/python`: 50 passed (`sdk_pytest.txt`).
- `web`: `npm run lint`, `npm run typecheck`, `npm run build` pass; Playwright (`PW_CHROMIUM_PATH=/opt/pw-browsers/chromium-1243/chrome-linux64/chrome npx playwright test`): **186 passed** (`playwright.txt`).
- `docker compose -p pk-m3 ... build`: all 17 images built (api and every worker from `backend/`, `mock-agent`, `web`); the stack ran for the QA-03 runs (`proof/QA-03/`).

## Notes
- `.env` needs `SECRET_KEY` (documented in `.env.example`); without it the `integrations` worker dead-letters every event (seen in the QA-03 stack, 80 rows).
- Docker Hub returned 429 on image metadata during a later rebuild; workers were re-tagged from the rebuilt `api` image (same Dockerfile).

STATUS: done-unverified (see commit SHA in report). Seed-fixture and language-evidence fixes are on `task/QA-03`, not here.
