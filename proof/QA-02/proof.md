# QA-02 proof: Kafka integration suite (duplicate, crash, DLQ, Kafka-down outbox drain in order)

Branch `task/QA-02` from `integrate/M2` @ 71a1022. Commit SHA: the last commit of `git log task/QA-02`. Dependency INFRA-02: present on `integrate/M2` (`proof/INFRA-02/proof.md`; real Kafka KRaft + Postgres). No production code changed; the suite only adds tests, a CI workflow and a runner script.

## What the suite adds beyond INFRA-02's own tests

INFRA-02 tested the framework on a database it assembled from `docs/schema.sql`. This suite runs on the database **Alembic** produces, writes **real domain rows** (`evaluations`, a plain INSERT so a second execution would violate the unique key) and uses a **real broker outage** and **real SIGKILLed processes**:

| File | TEST_PLAN row | What it proves (real Kafka, real Postgres) |
|---|---|---|
| `backend/tests/kafka/test_duplicate_and_crash.py` | NFR-4 | (1) the same `call.completed` delivered 4 times -> 1 evaluation, 1 `processed_events` row, every re-produced `evaluation.completed` carries one deterministic event id; (2) a consumer process is `SIGKILL`ed inside the handler (open transaction): no row, no offset commit; the next group member handles the redelivery once and exits 0 on SIGTERM; (3) `SIGKILL` after the DB commit but before the output / offset: the next member does **not** re-run the handler (it logs `REPRODUCE`), re-produces the output and commits; (4) a chain: 5 calls x 3 duplicate `call.completed` -> evaluator -> `evaluation.completed` -> a CRM-note consumer whose first attempt per call fails with a 503 (retry topic path): exactly 1 evaluation and 1 note per call, empty `dead_letters`, zero lag on the evaluator, notes consumer and retrier |
| `test_kafka_down_outbox.py` | NFR-4b | the broker container is **stopped** (`docker stop`): `GET /health` -> 503 with `kafka: down: ...` and `db: ok`; `POST /agents` still succeeds (201); 12 events (3 keys x 4, interleaved, one transaction each) are accepted into `outbox_events`; the real `OutboxRelay` tries, records `attempts` / `last_error`, loses nothing; the broker is **started**: backlog drains to 0, health back to 200, and for every key the events appear on the topic in enqueue order (deduplicated by event id; the number of at-least-once duplicates is printed) |
| `test_retry_dlq_throttle.py` | FR-RN-9 | three retryable failures -> attempts `[1,2,3]`, one message each on `retry.30s` (attempt 2) and `retry.5m` (attempt 3), one on `dlq.v1`, exactly one `dead_letters` row (open, attempts 3), no row left by any attempt, delays honoured; a permanent error skips the retry topics (attempts 1); a throttled event is retried three times with `x-reason: throttled`, attempt stays 1, never reaches `retry.5m` / DLQ / `dead_letters`, and is processed once the slot frees. Delays are scaled by the framework's `RetryPolicy`; the real 30 s / 5 min waits stay in INFRA-02's `test_real_delays.py` (measured 333 s) |
| `test_scale_consumers.py` | NFR-4c | two `ConsumerRunner`s with the same spec and settings split the 6 partitions disjointly, both handle events (30 events, every one exactly once); one leaves, the other takes all 6 partitions and handles the next 10; 40 `processed_events` rows for 40 events |

Helpers: `backend/tests/kafka/kit.py` (settings, seeding, in-process runners, `Broker` = Docker control found via `docker ps --filter publish=<host port>`), `crash_worker.py` (the killable consumer process).

## CI

`.github/workflows/kafka-suite.yml` starts `kafka` and `postgres` from `docker-compose.yml`, runs `kafka-init`, installs `requirements.txt` + `backend/requirements-dev.txt` and runs `scripts/ci/kafka_suite.sh` (`pytest tests/kafka tests/integration` with coverage). Compose is used instead of Testcontainers (the suite needs to stop and start the broker and to share one broker between processes). **The workflow has not run on GitHub from here** (nothing is pushed; the orchestrator owns merges). What was run: `scripts/ci/kafka_suite.sh --collect-only` and the full backend suite below against the same images (`apache/kafka:4.0.0`, `postgres:16`) started with `docker run` on non-default ports, because the sandbox already had other stacks on 5432 / 9094. The YAML parses (`yaml.safe_load`).

## Reproduce

```
docker compose up -d kafka postgres && docker compose up kafka-init
pip install -r requirements.txt -r backend/requirements-dev.txt
scripts/ci/kafka_suite.sh                                   # the CI subset: tests/kafka + tests/integration
cd backend && python3 -m pytest -p no:cacheprovider --cov=pareeksha -rs   # everything (pytest.txt)
ruff check . && ruff format --check . && python3 -m mypy                   # lint.txt
```
Overrides: `INFRA_TEST_KAFKA_BOOTSTRAP`, `TEST_DATABASE_URL`, `INFRA_TEST_DATABASE_URL` (see the header of `scripts/ci/kafka_suite.sh`).

## Results

PYTEST_SUMMARY

### The suite fails when the system is broken (mutation checks, files in this folder)
- `mutation_dedupe.txt`: the `processed_events` dedupe disabled in `events/consumer.py` -> 3 of the 4 duplicate / crash tests fail (the handler re-runs and the INSERT violates the unique key); the in-handler-kill test correctly still passes. File restored.
- `mutation_retry_budget.txt`: retry budget cut from 3 to 2 attempts -> `test_three_failures_walk_the_retry_topics_into_one_dead_letter` fails (message goes to the DLQ after 2 attempts). File restored.
- `mutation_outbox_order.txt`: relay ordering changed from `created_at, id` to `id` -> `test_api_accepts_while_kafka_is_down_and_the_outbox_drains_in_per_key_order` fails with "events left the outbox out of order". File restored.

## Not covered (blocked on tasks that are not in `integrate/M2`)
- `test_run_cap_and_outbox.py` (FR-RN-3): needs `POST /runs`, the planner and the run-slot reconciler (API-03) and the simulator (VOICE-05). The outbox half (an event and its domain row commit or roll back together) is covered by INFRA-02's `test_outbox.py`.
- `test_dlq_replay.py` (FR-IN-10): needs the DLQ replay / discard endpoints (API-04). The recorder's replayed -> open semantics are covered by INFRA-02's `test_retrier_and_recorder.py`.
- `test_outbound_idempotent.py` (FR-IN-5): needs the `integrations` consumer and a SQL `DeliveryStore` (INT-01 ships only the in-memory store). The consumer-level guarantee it relies on (a duplicate event runs the handler once) is test (1) above.
- NFR-4b's "API accepts" is shown with `POST /agents` and `/health` because `POST /runs` (API-03) does not exist yet; switch the request to `POST /runs` when it lands.
