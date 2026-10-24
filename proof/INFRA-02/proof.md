# INFRA-02 proof: consumer framework, producer, outbox relay, retrier, DLQ recorder

Branch `task/INFRA-02` (from `claude/amazing-einstein-agkccc` @ 51b62cd, M1 merged). Contracts untouched (`docs/contracts.md`, `backend/pareeksha/events/schemas.py`, `topics.py`).
Commit SHA: see the last line of this file (a commit cannot contain its own hash; the orchestrator can read it from `git log task/INFRA-02`).

## Built

| Module | What it does |
|---|---|
| `backend/pareeksha/events/consumer.py` | `@consumer(group, topic, reproduce=)`, `ConsumerRunner`, `Ctx`, `Outgoing`, `Throttled` / `RetryableError` / `PermanentError`, `classify()`, `RetryPolicy`. One message at a time, `enable_auto_commit=False`. Per message: parse envelope, then in one DB transaction insert `(group, event_id)` into `processed_events` and run the handler, commit, produce the returned events, **then** commit the Kafka offset. Failures: retryable -> copy with `attempt+1` to `retry.30s` / `retry.5m` (headers `x-target-topic`, `x-not-before`, `x-error`); permanent or attempt 3 exhausted -> `dlq.v1`; `Throttled` -> `retry.30s` with `x-reason: throttled` and the **same** attempt. Infrastructure faults (Kafka produce fails, Postgres connection drops in the framework's own SQL) do not consume an attempt: seek back, back off, redeliver. SIGTERM finishes the current message, commits, leaves the group. |
| `backend/pareeksha/events/producer.py` | `EventProducer`: `acks=all`, idempotent, bounded by a delivery timeout (aiokafka otherwise retries forever while the broker is down). |
| `backend/pareeksha/events/outbox.py` | `enqueue()` (same transaction as the domain rows), `relay_once()` (`FOR UPDATE SKIP LOCKED LIMIT 100`, publish, stamp `published_at`; failure records `attempts` / `last_error` and stops the batch), `prune_published()` (3 days), `backlog()`. |
| `backend/pareeksha/workers/outbox_relay.py` | `python -m pareeksha.workers.outbox_relay`: poll loop that survives Kafka or Postgres being down (backoff), prunes hourly. |
| `backend/pareeksha/workers/retrier.py` | Consumes both retry topics. Not-yet-due message: `seek` back + `pause` the partition until `x-not-before` while still polling (so the 5 min delay does not evict it from the group). Due: produce to `x-target-topic`, then commit. |
| `backend/pareeksha/workers/dlq_recorder.py` | `dlq.v1` -> `dead_letters` upsert on `(event_id, consumer_group)`; a replayed letter that fails again re-opens, a discarded one stays discarded; unparseable messages are stored as `{"raw": ...}`. |
| `backend/pareeksha/events/{settings,runtime}.py` | env settings, reconnecting DB connection, JSON log formatter, header helpers, signal handling. |
| `docker-compose.proxy.yml`, `docker-compose.yml` | proxy overlay now covers every backend-built service (workers); `outbox-relay`, `retrier`, `dlq-recorder` are real (profile `workers`). |

### Decisions and additions to the written design (all additive, no contract change)
1. **`reproduce=` callback.** TRD 10.4 says a redelivered duplicate re-produces its output events, but `processed_events` stores no outputs. A handler may pass a read-only `reproduce(env, ctx)` that rebuilds its outputs from DB state; without one a duplicate is skipped with a warning.
2. **`Outgoing.discriminator`.** Default output id is `uuid5(input_event_id, type)`. A fan-out (planner: one `run.requested` -> many `call.requested`) must set a discriminator (e.g. `run_item_id`) or the ids collide: `uuid5(input_event_id, "type:discriminator")`.
3. **`x-consumer-group` header** on retry / DLQ copies (not in the frozen header list). The retrier keeps it, so when `evaluation.completed` (finalizer + integrations) is retried only the group that failed reprocesses it; the other group skips and commits. Also gives `dead_letters.consumer_group`.
4. DLQ copies keep the envelope bytes unchanged, so `attempt` is the number of attempts made (3 for a retry-exhausted message, 1 for a permanent error).
5. Unknown exceptions are retried (bounded by 3 attempts); `ValueError` / `TypeError` / `KeyError` / pydantic `ValidationError` / HTTP 4xx (except 408, 429) / SQL data errors are permanent. See `classify()`.
6. Tables `outbox_events`, `processed_events`, `dead_letters` come from `docs/schema.sql` (API-01 turns them into Alembic). Tests and the demo create them by extracting those statements verbatim from `docs/schema.sql` (`tests/integration/support.py::plumbing_ddl`); they live in a separate database `pareeksha_events_test`, so nothing conflicts with API-01.
7. `outbox_events.created_at` is written with `clock_timestamp()` so events enqueued in one transaction keep their insert order when relayed.

## Reproduce

Bring up the stack (see `proof/INFRA-01/proof.md`; sandbox: the proxy overlay and `BUILDX_BAKE_ENTITLEMENTS_FS=0`; another container held port 5432 here, so Postgres was remapped to 55432 through an override file):
```
docker compose up -d kafka postgres && docker compose up kafka-init
pip install -r requirements.txt -r backend/requirements-dev.txt
cd backend
INFRA_TEST_DATABASE_URL=postgresql://pareeksha:pareeksha@localhost:5432/pareeksha_events_test \
  python -m pytest -v -rs --cov=pareeksha --cov-report=term-missing -p no:cacheprovider   # ~7.5 min, of which 5.5 min is the real-delay test
../proof/INFRA-02/lint.sh > ../proof/INFRA-02/lint.txt 2>&1
cd ..
./proof/INFRA-02/demo.sh > proof/INFRA-02/demo.txt 2>&1      # worker containers, real outage, real delays, group lag; ~7 min
```
Test settings: `INFRA_TEST_KAFKA_BOOTSTRAP` (default `localhost:9094`), `INFRA_TEST_DATABASE_URL`.

## Results (real output committed alongside)

### `pytest.txt`: 587 passed, 0 failed, 0 skipped; total coverage 96 %
New code: `events/consumer.py` 90 %, `events/producer.py` 91 %, `events/runtime.py` 85 %, `events/outbox.py` 100 %, `workers/outbox_relay.py` 85 %, `workers/retrier.py` 86 %, `workers/dlq_recorder.py` 87 %. The uncovered lines are start/stop/signal plumbing and exception branches of the infrastructure-fault backoff. `lint.txt`: `ruff check`, `ruff format --check`, `mypy` (strict) all clean.

Integration tests (`backend/tests/integration/`, real Kafka + Postgres, no mocks of either; 21 tests):

| SCOPE.md criterion | Test | What it proves |
|---|---|---|
| duplicate delivery gives one side effect | `test_duplicate_delivery_gives_one_side_effect` | same `event_id` sent twice: handler ran once, 1 side-effect row, 1 `processed_events` row, output re-produced with the same deterministic id, offsets committed (lag 0) |
| a crash mid-handler redelivers once | `test_kill_9_mid_handler_redelivers_and_processes_once` | a real subprocess is `SIGKILL`ed inside the handler: no side effect, no idempotency row, group lag 1; a second member of the group gets the message, handles it once, commits (lag 0), exits 0 on SIGTERM |
| offsets commit after the DB commit | `test_kill_9_after_db_commit_reproduces_output_without_second_side_effect` | process killed after the DB commit but before producing / committing the offset: DB rows exist, lag is still 1, no output yet; the next member sees a duplicate, does NOT rerun the handler, re-produces the output (deterministic id), commits |
| 3 failures land in the DLQ via retry.30s then retry.5m | `test_three_failures_go_through_retry_30s_and_retry_5m_to_dlq` (scaled delays) and `test_three_failures_with_real_30s_and_5m_delays_end_in_the_dlq` (real) | attempts `[1, 2, 3]`; exactly one copy each on `retry.30s` (attempt 2) and `retry.5m` (attempt 3) and `dlq.v1`; failed attempts rolled back (no side effect, no `processed_events`); `dead_letters` row (attempts 3, status open); consumer / retrier / recorder lag 0. Real-delay test measured gaps between handler calls: 30 s <= gap1 < 45 s and 300 s <= gap2 < 315 s (test passed in 333 s) |
| the throttle path works | `test_throttle_does_not_consume_attempts` | 3 throttles, 4th call succeeds: every call saw `attempt == 1`, three `retry.30s` copies with `x-reason: throttled` and `attempt` 1, nothing on `retry.5m` / DLQ |
| (NFR-4) permanent errors skip retries | `test_permanent_error_goes_straight_to_dlq` | attempts 1, nothing on retry topics |
| poison messages | `test_unparseable_and_unknown_type_messages_go_to_dlq` | invalid JSON and an unknown event type reach `dead_letters` (raw text stored); handler never called |
| retry then success | `test_retryable_failure_then_success_processes_once` | attempts `[1, 2]`, one side effect, no DLQ |
| group-targeted retries | `test_copy_for_another_group_is_skipped_but_committed` | |
| output ids | `test_output_event_ids_are_deterministic_and_discriminated` | `uuid5(input, type[:discriminator])`, `causation_id`, `correlation_id`, producer name |
| retrier timing | `test_retrier_pauses_until_not_before_then_redelivers_with_group_header` (+ misrouted message test) | message delivered only after `x-not-before`; headers rewritten; retrier lag 0; message without `x-target-topic` is parked in the DLQ |
| DLQ recorder | `test_recorder_is_idempotent_and_reopens_replayed_letters_only` | duplicate DLQ delivery is a no-op, replayed -> open, discarded stays |
| outbox | `tests/integration/test_outbox.py` (7 tests) | rolled-back transaction leaves no event; committed one is published once; 3 concurrent relays publish 30 rows exactly once (SKIP LOCKED); broker failure mid-batch keeps unpublished rows with `attempts` / `last_error`, then drains; relay worker survives unreachable Kafka and stops cleanly; pruning; send timeout |

Unit tests: `backend/tests/unit/test_consumer_logic.py` (error classification, registry, dead-letter building, headers, settings, log format).

### `demo.txt`: the same machinery as separate worker containers on the compose stack
(final run on a freshly reset stack; consumer lag and offsets are `kafka-consumer-groups.sh --describe` output)
- Tables applied from `docs/schema.sql`; `outbox-relay`, `retrier`, `dlq-recorder` built and started from the backend image.
- **Outbox:** 5 events enqueued in one DB transaction -> relay log `outbox published 5 event(s)`; `unpublished 0 | published 5`.
- **Real Kafka outage:** `docker compose stop kafka`; 3 more events enqueued (DB write works); after 30 s `unpublished 3`, `last_error = TimeoutError`, relay logged the failure and backed off; `docker compose start kafka`; 18 s later `unpublished 0 | total 8`.
- **Retry + DLQ with the real delays**, consumer group `demo-flaky` (always fails retryably) next to the real `retrier` and `dlq-recorder` containers: handler calls at 02:11:22 (attempt 1), 02:11:52 (attempt 2, +30 s), 02:16:53 (attempt 3, +301 s), then DLQ; `dead_letters` row `demo-flaky | pareeksha.audit.requested.v1 | 3 | open`; the three topic copies are printed with their `x-target-topic`, `x-error`, `x-consumer-group`, `x-not-before` headers.
- **Consumer-group offsets and lag:** `demo-flaky`, `retrier`, `dlq-recorder` all `LAG 0` at the end.
- **Graceful shutdown:** SIGTERM to the host consumer and `docker compose stop` of the three workers: all exit code 0.

## Not covered / follow-ups
- Per-run slot take/release SQL (`active_calls`) and the reconciler are API-03 / EVAL-03; this task provides only the `Throttled` mechanism.
- `/metrics/summary` consumer-lag admin queries are API-04.
- Compose workers for planner, simulator, auditor, evaluator, finalizer, integrations, dialect, generator still do not exist (their tasks).
- `testcontainers` is not used: QA-02 can reuse `tests/integration/support.py` and `harness.py` against Compose, or wrap them.

## Tracked stubs
None (`grep -rn "STUB(" backend/pareeksha/events backend/pareeksha/workers` is empty).
