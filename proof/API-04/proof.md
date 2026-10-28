# API-04 proof: runs SSE, run compare/report, DLQ list/replay/discard, `/metrics/summary`, calls API

Branch `task/API-04` from `integrate/M2` @ 71a1022 (+ API-03 `c0ca61d`). Commit SHA: last commit of `git log task/API-04`. Contracts untouched. All 11 `STUB(API-04)` handlers replaced (none left: `grep -rn "STUB(API-04)" backend/pareeksha` is empty).

## Built
- `GET /runs/{id}/events` (SSE, `runs/stream.py`): snapshot first, then `pareeksha.progress.v1` events; `id:` encodes the last offset per partition so `Last-Event-ID` resumes without loss (at-least-once; clients apply idempotently); ends after `run.completed`.
- `GET /runs/compare` (`runs/compare.py`) per-cell deltas; `GET /runs/{id}/report` HTML (`runs/report.py`).
- `GET /dlq`, `POST /dlq/{id}:replay|:discard` (`ops/dlq.py`): replay keeps the original `event_id`, new outbox row.
- `GET /metrics/summary` (`ops/metrics.py`): consumer lag, outbox backlog, DLQ count; `GET /usage`.
- Calls API: list / detail / audio with Range (`calls/service.py`, `calls/audio.py`).

## Reproduce
```
docker compose -p api04 -f docker-compose.yml -f proof/API-04/compose.override.yml up -d kafka postgres && ... up kafka-init
export DATABASE_URL=postgresql+psycopg://pareeksha:pareeksha@localhost:61432/pareeksha TEST_DATABASE_URL=$DATABASE_URL \
  INFRA_TEST_DATABASE_URL=postgresql://pareeksha:pareeksha@localhost:61432/pareeksha_events_test INFRA_TEST_KAFKA_BOOTSTRAP=localhost:61094
cd backend && python3 -m pytest -p no:cacheprovider --cov=pareeksha     # pytest.txt
../proof/API-04/lint.sh                                                  # lint.txt
cd .. && CA_BUNDLE=/root/.ccr/ca-bundle.crt ./proof/API-04/capture.sh > proof/API-04/e2e.txt 2>&1   # real Postgres + Kafka + API/planner/relay/dlq-recorder containers
```

## Results
- `pytest.txt`: 879 passed, 0 failed, 0 skipped, coverage 97% (first run, interrupted builder). Re-run this session on a clean sandbox: 875 passed + the 4 entry-point tests that need `pip install -e backend` (then 73/73 in `tests/unit/integrations`); new modules: calls/audio 97%, ops/metrics 92%, runs/report 90%, runs/stream 96%, routers/system 97%.
- `lint.txt`: ruff clean, `ruff format --check` clean, mypy clean on the original run. In this sandbox mypy additionally reports 2 errors in `tests/unit/speech/test_deepgram.py` (VOICE-07 code, websockets 15 typing of `server.sockets`), not API-04.
- `e2e.txt` (this session, 0 TIMEOUTs): API JSON printed next to the DB rows it must match, for each section: calls list/detail vs `calls`/`turns`/`evaluations`; audio full/Range/416; compare vs both runs' evaluations; report HTML; `/usage` + `/metrics/summary` vs `api_usage`; SSE connect, drop, planner restart, reconnect with `Last-Event-ID` receiving the 6 missed events, live stream through cancel; outbox backlog with the relay stopped; DLQ bus -> planner -> `dead_letters` -> replay -> discard.

## Caveat
Calls/turns/evaluations in the e2e are seeded by `seed_results.py` because the simulator / evaluator workers belong to other tasks; runs themselves go through `POST /runs` and the real planner.
