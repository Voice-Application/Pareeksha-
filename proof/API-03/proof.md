# API-03 proof: runs API, planner consumer, run slots and reconciler

Branch `task/API-03`, created from `integrate/M2` @ 71a1022. Contracts untouched (`docs/contracts.md`, `events/schemas.py`, `topics.py`, `schemas/runs.py`). Commit SHA: `git log -1 task/API-03` (a commit cannot contain its own hash).

## Built

| Module | What it does |
|---|---|
| `backend/pareeksha/api/routers/runs.py` | The 6 `STUB(API-03)` handlers are real: `POST /runs`, `POST /runs:estimate`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/items`, `POST /runs/{id}/cancel`. (`compare`, `events` SSE and `report` stay `STUB(API-04)`.) |
| `backend/pareeksha/runs/service.py` | API side: validation, estimate/budget (402), run + outbox in one transaction, progress buckets, list filters and cursor paging, items joined with scenario / persona / profile names, call and latest evaluation, cancel. |
| `backend/pareeksha/runs/estimate.py` | Cost estimate from the `COST_*` rates and `BUDGET_CREDITS` minus `api_usage.est_cost`. |
| `backend/pareeksha/runs/matrix.py` | Matrix expansion; deterministic per-item seeds. |
| `backend/pareeksha/runs/slots.py` | `take_slot` (the TRD 10.6 statement), `release_slot`, `start_item` (slot + item `connecting` in one transaction; `TAKEN / RESUMED / THROTTLED / SKIPPED`), `reconcile_slots`. This is what the simulator (VOICE-05) calls. |
| `backend/pareeksha/workers/planner.py` | `python -m pareeksha.workers.planner`, group `planner`: `run.requested` -> `run_items` -> `call.requested` (key `run_item_id`, `Outgoing.discriminator = run_item_id`) + `item.status` progress events; `reproduce=` for duplicates. Handles regression runs and an empty suite. |
| `backend/pareeksha/workers/reconciler.py` | `python -m pareeksha.workers.reconciler`: every 60 s recomputes `active_calls` from `run_items`; survives an unreachable database. |
| `backend/pareeksha/events/outbox.py` | additive `enqueue_session(session, envelope)` so the API writes the outbox row through its SQLAlchemy session (same transaction as the run). |
| `docker-compose.yml`, `docker-compose.proxy.yml` | new `reconciler` service (profile `workers`); `planner` is now real. |
| `backend/Dockerfile` | installs `sqlalchemy[asyncio]` (was `sqlalchemy`): without `greenlet` the API/seed containers died at import (found while building this proof). |
| `docs/06-api-spec.md`, `NOTES.md` | behaviour notes. |

### Decisions (all within the frozen contracts)
1. **Slot and item change together.** `start_item` locks the run row, then the item, takes the slot and sets the item `connecting` in one transaction; a redelivered message finds an active item and returns `RESUMED` without a second slot. At the cap it returns `THROTTLED` and the simulator raises `Throttled` (INFRA-02: `retry.30s`, attempt unchanged).
2. **Reconciler locks first, counts second.** A single `UPDATE ... SET active_calls = (SELECT count(*) ...)` can write a stale count if a `take_slot` commits while it waits for the row lock, so it takes `FOR UPDATE` on the run and counts in a separate statement. "Active" = item status `connecting` / `in_progress`. TRD puts the reconciler "in finalizer"; no finalizer worker exists yet, so it is its own small worker (needs only Postgres).
3. **Seeds are derived from the cell**, `sha256(run_seed:scenario:persona:profile:repeat[:salt])` (63 bit), so planning twice yields the same rows (`ON CONFLICT DO NOTHING` on the table's unique key). Regression tests on the same cell get a `salt` (the test id). A regression test without persona / noise profile falls back to the project's oldest persona / profile.
4. **Limits I chose** (not in the spec): at most 1000 calls per run (400 `validation_error` with `details {item_count, max_items}`), repeated ids in a list count once, an archived agent is 409, unknown or other-project references are 404.
5. **Estimate model** (assumption, constants at the top of `runs/estimate.py`): 6 s per turn capped by the agent's `max_call_seconds`, caller speaks half the turns, 15 characters of TTS per second, STT on both sides, token sizes per caller / judge call. Unset `COST_*` rates count as 0 (so `est_cost` is 0.0 and the budget guard cannot trip until the owner has filled them; the capture below runs with no rates). `kind: dry_run` is estimated without speech. No `BUDGET_CREDITS` = no guard.
6. **Cancel**: queued items -> `cancelled`, run -> `cancelled`, an `item.status` progress event per cancelled item and a `run.completed` progress event go to the outbox in the same transaction; calls already in flight finish and are evaluated. A finished or already cancelled run is 409. (A later finalizer must not overwrite `cancelled`; that is EVAL-03 / VOICE-05 territory.)
7. The cap `max_concurrency` comes from `test_runs.config`; a run row without it falls back to 3 (the API default).

## Reproduce

```
docker compose -p api03 -f docker-compose.yml -f proof/API-03/compose.override.yml up -d kafka postgres
docker compose -p api03 -f docker-compose.yml -f proof/API-03/compose.override.yml up kafka-init
pip install -r requirements.txt -r backend/requirements-dev.txt
cd backend
TEST_DATABASE_URL=postgresql+psycopg://pareeksha:pareeksha@localhost:35432/pareeksha \
INFRA_TEST_DATABASE_URL=postgresql://pareeksha:pareeksha@localhost:35432/pareeksha_events_test \
INFRA_TEST_KAFKA_BOOTSTRAP=localhost:39094 \
  python3 -m pytest -rs --cov=pareeksha --cov-report=term-missing -p no:cacheprovider   # ~9 min (5.5 min is INFRA-02's real-delay test)
../proof/API-03/lint.sh > ../proof/API-03/lint.txt 2>&1
cd .. && CA_BUNDLE=/root/.ccr/ca-bundle.crt ./proof/API-03/capture.sh > proof/API-03/e2e.txt 2>&1   # ~5 min, builds the images
```
Sandbox: another project on this host held 5432 / 9094 / 8000, so `proof/API-03/compose.override.yml` remaps Postgres to 35432, the Kafka host listener to 39094 and the API to 38000; `CA_BUNDLE` + `BUILDX_BAKE_ENTITLEMENTS_FS=0` for the image build behind the proxy. Do not run the pytest suite while the planner container is up on the same broker: the tests publish `run.requested` for throw-away databases, and the container's planner would dead-letter them (this happened once, see below).

## Results

### `pytest.txt`: 868 passed, 0 failed, 0 skipped; total coverage 97 %
New code: `runs/service.py` 99 %, `runs/slots.py` 96 %, `runs/matrix.py` / `runs/estimate.py` 100 %, `workers/planner.py` 93 %, `workers/reconciler.py` 85 % (uncovered: signal entry point `main()`), `events/outbox.py` 100 %. `lint.txt`: `ruff check`, `ruff format --check`, `python3 -m mypy` (strict) clean.

New tests (real Postgres via Alembic, real Kafka, no mocks of either), by SCOPE.md criterion:

| Criterion | Tests |
|---|---|
| `POST /runs` writes run and outbox row in one transaction (FR-RN-1) | `test_runs_api.py::test_create_run_writes_run_and_run_requested_outbox_row` (run row, `agent_snapshot` without secrets, outbox row `run.requested` keyed by run_id with every payload field, unpublished, no items yet); `test_run_and_outbox_row_commit_or_roll_back_together` (outbox failure after the run was flushed leaves no run) |
| estimate and budget (FR-RN-2) | `test_estimate_creates_nothing_and_matches_create`, `test_over_budget_run_gets_402_with_the_estimate_unless_confirmed` (402 + estimate + remaining budget, nothing written, `confirm_over_budget` forces 201), `test_remaining_budget_subtracts_api_usage`, `test_dry_run_estimate_has_no_speech` |
| validation, scopes, project isolation | `test_create_validates_references_and_is_project_scoped`, `test_archived_agent_cannot_start_a_run`, `test_duplicate_ids_are_collapsed_and_oversized_matrices_refused`, `test_scopes_...`, `test_run_reads_are_project_scoped`, `test_read_key_cannot_cancel` |
| read side (runs, list filters + paging, items, progress) | `test_get_run_before_and_after_planning_and_progress_buckets`, `test_list_runs_filters_and_pages`, `test_items_listing_joins_names_call_and_latest_evaluation` |
| cancel | `test_cancel_cancels_queued_items_and_tells_the_live_view`, `test_cancel_refuses_a_finished_run` (completed / partial / failed -> 409) |
| planner expands the matrix, `call.requested` keyed by run_item_id (FR-RN-3) | `test_planner.py::test_post_runs_to_call_requested_end_to_end` (API -> outbox -> real relay -> Kafka -> planner consumer: 24 items for 3x2x2x2, seeds as the matrix says, 24 `call.requested` keyed by `run_item_id` over several partitions, ids `uuid5(run.requested id, "call.requested:<item>")`, `causation_id`, 24 `item.status queued` progress events, planner group lag 0); `test_redelivered_run_requested_adds_no_items_and_reproduces_the_events` (same event twice: 4 items, 1 `processed_events` row, 8 messages with 4 distinct ids); `test_planning_twice_leaves_the_same_items`, `test_items_that_already_started_are_not_requested_again`, `test_a_cancelled_run_is_not_planned`, `test_a_run_that_does_not_exist_is_a_permanent_error`; regression: one item per selected test (distinct seeds, `regression_test_id`), persona fallback, empty suite completes the run and emits `run.completed` |
| run slots never exceed the cap (NFR-4b) | `test_run_slots.py::test_concurrent_simulators_never_exceed_max_concurrency` (12 connections, cap 3: exactly 3 `TAKEN`, 9 `THROTTLED`), `test_a_released_slot_goes_to_the_next_waiting_item`, `test_cap_comes_from_each_runs_config_and_defaults_to_three`, `test_redelivery_resumes_the_item_without_a_second_slot`, `test_cancelled_finished_and_unknown_items_are_skipped`, `test_release_never_goes_below_zero`, `test_reconciler_is_safe_while_simulators_run` (30 start/release cycles interleaved with continuous reconciliation and a sampler: peak never above the cap, ends at 0 with all 30 completed) |
| the reconciler repairs a leaked slot | `test_reconciler_repairs_a_leaked_slot_and_a_missing_one` (counter too high, too low, healthy run untouched, idempotent, a run held at its cap by a leak can start again), `test_reconciler_worker_repairs_on_its_interval_and_stops_cleanly`, `test_reconciler_worker_survives_an_unreachable_database` |
| throttle path on Kafka | `test_throttled_calls_wait_in_retry_30s_without_using_an_attempt` (a consumer on the real framework using `start_item`: cap 2 of 5 -> 2 started, 3 copies on `retry.30s` with `x-reason: throttled`, `attempt` still 1) |
| no stubs left | `tests/unit/test_runs_logic.py` (no `STUB(API-03)` in the source, route table), `tests/contract/test_stub_routes.py` (no 501 route owned by API-03); matrix / estimate unit tests |

### `e2e.txt`: the same path on the compose stack (api, outbox-relay, planner, reconciler containers)
Run `6e2a3822-0d68-4315-ab92-95cf89773a66` (3 scenarios x 2 personas x 2 noise profiles of the seed data, `max_concurrency` 3):
- `POST /runs` -> 201 `{status: queued, item_count: 12}`; `POST /runs:estimate` returns the same estimate and creates nothing (rates unset, so `est_cost` 0.0).
- Outbox row `pareeksha.run.requested.v1`, key = run id, `published = t` (relay), event id `6ed6bf62-...`.
- Planner container: `planned run ...: 12 item(s)`; `run_items` shows 12 rows `queued` with scenario / persona / noise profile names and distinct seeds.
- Kafka: 12 `call.requested` messages, key = `run_item_id`, spread over partitions 0, 1, 2, 3, 5 (offsets printed), each `causation_id = 6ed6bf62...`.
- Consumer group `planner` (`kafka-consumer-groups --describe`): `CURRENT-OFFSET == LOG-END-OFFSET`, **LAG 0** on every partition, before and after the rest of the run.
- Slots: 12 simulators race (`slots_demo.py`): `{'taken': 3, 'throttled': 9}`, `active_calls = 3`, run `queued -> running`, items 3 `connecting` + 9 `queued`.
- Reconciler: `active_calls` forced to 7 while 3 items are really active; the reconciler container logs `repaired run slot counter` and the counter is back to 3.
- `GET /runs/{id}`: `progress {total 12, queued 9, in_progress 3}`; `/items` paged with `next_cursor`; `GET /runs` lists the run.
- `POST /runs/{id}/cancel` -> 202 `cancelled`; items: 9 `cancelled`, 3 `connecting` (in flight); a second cancel is 409 `conflict`.
- The planner group also shows 6 earlier `run.requested` messages that my pytest run had published to the same broker (runs in throw-away databases). The planner container logged `PermanentError: run ... does not exist -> DLQ after 1 attempt(s)` for each: an unplanned side effect of sharing the broker, and incidentally the permanent-error path working (no retrier / dlq-recorder containers were up, so they sit on `dlq.v1`).

## Not covered / follow-ups
- The simulator that calls `start_item` / `release_slot` is VOICE-05; the finalizer's handling of a `cancelled` run is EVAL-03 / VOICE-05; `GET /runs/{id}/events` (SSE), compare, report are API-04; `POST /runs:regression` is API-05 (the planner already handles `kind: regression`).
- `est_cost` is 0 until the owner fills the `COST_*` rates in `.env`; the model constants are assumptions to tune once calls are measured.
- Real-key acceptance is not involved: nothing in API-03 calls Gnani or an LLM.

## Tracked stubs
None in files this task owns (`grep -rn "STUB(API-03)" backend` is empty). Remaining `STUB(API-04)` / `STUB(API-05)` markers belong to other tasks.
