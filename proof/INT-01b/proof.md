# INT-01b proof: SQL delivery store, integrations consumer, delivery routes

Branch `task/INT-01b` from `integrate/M2` @ 71a1022. Contracts untouched. Commit SHA: last line of this file.

## Built

| Piece | Where |
|---|---|
| SQL `DeliveryStore` over `integration_deliveries` | `backend/pareeksha/integrations/sql_store.py` (`PsycopgDeliveryStore`: `claim` = `INSERT .. ON CONFLICT DO NOTHING RETURNING`, `save`, `get`, `recent`). The `DeliveryStore` protocol in `delivery.py` is now async; `InMemoryDeliveryStore` follows it. |
| Fan-out service | `backend/pareeksha/integrations/dispatch.py`: project of the event, enabled sink integrations, `event_filter` (events / agent_ids / only_failed / min_score_below), `EvaluationSummary` rebuilt from calls + evaluations + agents + scenario/persona (no transcript), delivery per integration, `redeliver()`. |
| Kafka consumer | `backend/pareeksha/workers/integrations.py` (group `integrations`, topics `evaluation.completed` + `run.completed`, on the INFRA-02 `@consumer` framework). Compose service `integrations` (profile `workers`) already pointed at `python -m pareeksha.workers.integrations`; it now exists. |
| 3 routes (STUB(INT-01) removed) | `POST /integrations/{id}/test` (runs the connector `test()`, stores `last_test_at/ok`, a bad config is `ok:false` naming the fields, never values), `GET /integrations/{id}/deliveries` (status filter, cursor pagination, project scoped), `POST /integrations/{id}/deliveries/{did}/redeliver` (202; admin; 404 / 409 when the row has no stored event). `backend/pareeksha/api/routers/integrations.py`. |
| `hubspot` entry point | It was already declared in `backend/pyproject.toml` (`hubspot = "pareeksha.integrations.hubspot:HubSpotConnector"`); the editable install in the checkout pointed at another worktree, so `entry_points()` did not show it. After `pip install -e backend --no-deps` `GET /integrations/connectors` lists `hubspot` and `webhook` (test `test_connectors_route_lists_webhook_and_hubspot`). The fallback `SHIPPED_DIRECTIONS` in `api/connectors.py` is removed; the registry is the only source. |
| STUB(API-02) | None left in `backend/pareeksha` (`grep -rn "STUB(API-02)" backend/pareeksha` is empty; `tests/unit/test_no_api02_stubs.py` enforces it; the only text matches are that test and `proof/API-02/proof.md`). Nothing to implement. |

### Design decisions
1. **Rows live on a separate autocommit connection**, not in the consumer's transaction. A handler failure rolls back `processed_events` (so the event is retried) but must not roll back "integration A already posted"; with the row on its own connection, A is terminal on the retry and only the failed integration is re-sent. The claim and the incremented `attempts` are saved before `handle()`, so a crash leaves a durable `pending` row.
2. **Retryable failure of one integration does not stop the others**: all matching sinks are tried, then `RetryableError` is raised once (retry.30s / retry.5m). On the last attempt (`ctx.attempt >= 3`) the row is saved as `failed` so the log never says `pending` for a message that went to the DLQ.
3. **Redelivery** stores the event envelope (ids and scores only, no transcript, no secrets) in `request_summary.envelope`; `redeliver` resets the row to `pending`, rebuilds the summary from the database and sends under the same event id. It runs in the API request (no Kafka hop), so a retryable failure there is recorded as `failed`.
4. **Webhook sink sends `X-Pareeksha-Event-Id`** (stable across retries/redelivery). Delivery on the wire is at-least-once; a receiver dedupes on that id, like the receiver used here.
5. **Dev switch** `PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1` (webhook connector only, logs a WARNING) turns off just the "resolved address must be public" check so a receiver on localhost can be used. https, no credentials and IP pinning stay on. Off by default; the SSRF tests still pass and `test_ssrf_guard_applies_to_the_test_route` proves it is enforced when unset.

## Reproduce

```
docker compose up -d kafka postgres && docker compose up kafka-init     # or any Kafka + Postgres
pip install -e backend --no-deps; pip install -r requirements.txt -r backend/requirements-dev.txt
cd backend
export INFRA_TEST_KAFKA_BOOTSTRAP=localhost:9094 \
       INFRA_TEST_DATABASE_URL=postgresql://pareeksha:pareeksha@localhost:5432/pareeksha_events_test \
       TEST_DATABASE_URL=postgresql+psycopg://pareeksha:pareeksha@localhost:5432/pareeksha
python -m pytest -rs --cov=pareeksha --cov-report=term-missing -p no:cacheprovider   # ~9.5 min (5.5 min is the real-delay test)
ruff check . && ruff format --check . && python3 -m mypy
PYTHONPATH=. python ../proof/INT-01b/demo.py        # ~40 s, prints DB rows and receiver counts
```
The proof run used a private Kafka (`apache/kafka:4.0.0`, topics from `infra/kafka/create-topics.sh`) and Postgres 16 in Docker, because the shared broker on this machine also carried other tasks' traffic.

## Results

`pytest.txt`, `lint.txt`, `demo.txt` are the real outputs (see the end of this file for the numbers).

New tests (real Kafka, real Postgres, real HTTPS receiver with HMAC verification; the worker is the real `python -m pareeksha.workers.integrations` process):

| Criterion | Test | Proves |
|---|---|---|
| delivery log rows | `test_evaluation_completed_is_delivered_signed_and_logged` | one signed POST (signature verified by the receiver), body has event id, agent, score, failing dimensions, CRM metadata, deep link, no transcript; DB row `succeeded / attempts 1 / http 200 / outbound`; `GET .../deliveries` shows it; offset committed |
| duplicate delivery gives one delivery | `test_duplicate_kafka_delivery_gives_one_delivery` | same event id published 3 times: receiver 1 POST, 1 delivery row, 1 `processed_events` row |
| crash gives one delivery | `test_kill_9_during_the_http_call_still_gives_one_delivery` | worker SIGKILLed while the receiver holds the response: row is `pending`, attempts 1, offset uncommitted; a second worker redelivers: exactly 1 row `succeeded` (attempts 2), 1 unique event id at the receiver (2 POSTs on the wire: the dead process's and the retry), lag 0 |
| filters | `test_event_filter_and_disabled_integrations_are_respected` | only_failed and disabled integrations get nothing |
| SQL store | `test_store_claim_is_unique_*`, `test_concurrent_claims_create_one_row` (8 concurrent claims, 1 creator), autocommit guard, FK |
| retry / DLQ semantics | `test_retryable_failure_keeps_the_row_pending_then_failed_on_the_last_attempt`, `test_permanent_failure_is_logged_failed_without_retry`, `test_one_failing_integration_does_not_block_the_others` | 503 -> pending + `DeliveryRetry`; last attempt -> `failed`; 404 -> `failed`, no retry; terminal rows never re-sent; others still delivered |
| tenancy | `test_missing_evaluation_and_other_projects_are_not_delivered` | other project's integration gets nothing |
| routes | `test_test_route_*`, `test_ssrf_guard_applies_to_the_test_route`, `test_deliveries_route_filters_paginates_and_is_project_scoped`, `test_redeliver_*` | see design above; 403 for read keys, 404 across projects, 409 without stored event |
| unit | `tests/unit/integrations/test_dispatch_and_dev_switch.py` | filters, dev switch default off, no `STUB(INT-01)` left |

`demo.txt` (same machinery, printed straight from Postgres): A one event -> row `succeeded 1 200`, receiver 1 POST, signatures valid; B same event 3 more times -> still 1 row, 1 POST, `processed_events` 1; C kill -9 mid-request -> row `pending 1`, offset not committed, after restart row `succeeded 2 200`, receiver saw 1 unique event id.

## Not covered / follow-ups
- HubSpot is exercised through the same pipeline only by INT-02's mocked unit tests; the live HubSpot run is still pending the owner token (INT-02).
- `run.completed` fan-out works and is filtered, but only the webhook connector subscribes to it; no test publishes a real `run.completed` through Kafka.
- Redeliver is synchronous inside the API request (webhook timeout up to `timeout_s`, default 10 s).
- The 3 failures of the earlier full run on the shared broker (`test_real_delays`, two retrier tests) came from other tasks' consumers on the same topics; they are green on the private broker.

## Tracked stubs
None in files I own. Remaining `STUB(...)` markers belong to other tasks (EVAL-05, API-03/04/05, EVAL-04, VOICE-04).

## Final numbers
`pytest.txt`: **848 passed, 0 failed, 0 skipped**, total coverage 97 % (dispatch 88 %, sql_store 96 %, routers/integrations 99 %, webhook 99 %; `workers/integrations.py` shows 0 % only because it runs as a subprocess in the tests, which coverage does not measure; its handler is exercised end to end by the three worker tests). `lint.txt`: ruff check, ruff format --check and mypy strict all clean.
Code commit: 52a4029 (branch task/INT-01b)
