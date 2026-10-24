# EVAL-03b proof: evaluator and finalizer on the consumer framework, Postgres stores, `api_usage`

Branch `task/EVAL-03b` from `integrate/M2` @ 71a1022. Completes EVAL-03 (`proof/EVAL-03/proof.md` lists what was left).
Commit SHA: see `git log task/EVAL-03b` (a commit cannot contain its own hash).

## Built

| Piece | Where |
|---|---|
| `evaluator` consumer, group `evaluator`, topic `call.completed`, with `reproduce=` | `backend/pareeksha/workers/evaluator.py` (`python -m pareeksha.workers.evaluator`) |
| `finalizer` consumer, group `finalizer`, topic `evaluation.completed`, with `reproduce=` | `backend/pareeksha/workers/finalizer.py` |
| Postgres `EvaluatorStore` / `FinalizerStore` (+ read ports) bound to `ctx.tx` | `backend/pareeksha/evaluation/pg_stores.py` |
| `api_usage` rows from the LLM `usage_sink` | `backend/pareeksha/llm/usage_db.py` |
| Handler refactor: `evaluation_outputs`, `reproduce_call_completed`, `run_completed_outputs`, `reproduce_run_completed` | `backend/pareeksha/evaluation/handlers.py` |
| `Outgoing.event_id` (optional explicit id, additive) | `backend/pareeksha/events/consumer.py` |
| Compose: `evaluator` (2 replicas) and `finalizer` under profile `workers` now real; LLM env passthrough (`LLM_PROVIDER`, `DEEPSEEK_API_KEY`, `COST_DEEPSEEK_*`) | `docker-compose.yml` |
| Image fixes found while running the containers: `rapidfuzz` (imported by evaluation checks) and `sqlalchemy[asyncio]` (greenlet, seed CLI) | `backend/Dockerfile`, `backend/pyproject.toml` |

How the pieces give exactly one evaluation:
- The framework inserts `(evaluator, event_id)` into `processed_events`, runs the handler and commits in ONE transaction. The store writes `evaluations` (upsert on `(call_id, rubric_version_id)`, deterministic row id), replaces `deterministic_checks`, upserts `call_metrics` and sets `run_items.status` (`evaluated` / `judge_error`) on that same transaction.
- Duplicate delivery of the same `event_id`: the handler (and the judge) is skipped; `reproduce` rebuilds `evaluation.completed` and `call.evaluated` from the stored row with the same deterministic ids.
- SIGKILL before the commit: nothing persisted, offset uncommitted, the next group member judges the redelivered message once. SIGKILL after the commit and before the offset commit: the next member takes the duplicate path (no judge call).
- A different `event_id` for the same call (upstream re-emission) re-runs the judge but cannot add a second row (`UNIQUE (call_id, rubric_version_id)`).
- Finalizer: `claim_run_completion` = `UPDATE test_runs ... WHERE id=? AND finished_at IS NULL AND status IN ('queued','running','cancelled') RETURNING id`; `run.completed` id = `uuid5(run_id, "run.completed")`.
- `api_usage`: one row per provider call (`provider`, `operation=llm_judge`, `units`=tokens, `est_cost`, `run_id`, `call_id`), written on its own connection so a rolled-back evaluation still records the spend it caused; an insert failure is logged with the full record and never fails the evaluation.
- LLM errors map to framework dispositions: `LLMPermanentError` -> `PermanentError` (DLQ), `LLMRetryableError` -> `RetryableError` (retry.30s -> retry.5m), unknown call -> permanent, missing rubric row -> retryable.

## Reproduce

```
docker compose up -d kafka postgres && docker compose up kafka-init      # sandbox: see proof/EVAL-03b/sandbox_override.yml
pip install -e "backend[dev]" rapidfuzz audioop-lts                      # audioop-lts on Python 3.13
cd backend
INFRA_TEST_DATABASE_URL=postgresql://pareeksha:pareeksha@localhost:55432/pareeksha_events_test \
TEST_DATABASE_URL=postgresql+psycopg://pareeksha:pareeksha@localhost:55432/pareeksha \
  python3 -m pytest -rs --cov=pareeksha --cov-report=term-missing -p no:cacheprovider   # ~11 min (5.5 min is INFRA-02's real-delay test)
ruff check . && ruff format --check . && python3 -m mypy
cd .. && ./proof/EVAL-03b/acceptance.sh > proof/EVAL-03b/acceptance.txt 2>&1   # needs DEEPSEEK_API_KEY; one real judge call
```

## Results

### Tests: `pytest.txt`: 847 passed, 0 failed, 0 skipped; total coverage 97 %
New modules: `workers/evaluator.py` 81 %, `workers/finalizer.py` 85 %, `evaluation/pg_stores.py` 90 % (uncovered: judge_error / no-scenario / cancelled-run branches and the real `get_client` path's run loop), `llm/usage_db.py` and `workers/_outgoing.py` 100 %.
Lint (`lint.txt`): `ruff check`, `ruff format --check`, `python3 -m mypy` (strict, 186 files) all clean.

GOAL item 6 for evaluations, real Kafka + real Postgres (full `docs/schema.sql` schema in a throwaway database per test), production consumers and stores, scripted judge (countable, free): `backend/tests/integration/test_evaluator_exactly_once.py`

| Test | What it proves (DB query + topic read in the test) |
|---|---|
| `test_duplicate_delivery_gives_one_evaluation_row` | the same `call.completed` event published twice: `evaluations` = 1 row, judge called once, one `processed_events` row; `evaluation.completed` re-produced with the same event id; a second, different event for the call re-judges but the table stays at 1 row; `run_items` = `evaluated`, `deterministic_checks` and `call_metrics` written, `api_usage` row per real judge call with tokens, cost, run and call ids |
| `test_sigkill_during_judge_call_gives_one_evaluation_row` | a real subprocess is SIGKILLed inside the judge call: 0 evaluations, 0 `processed_events`, group lag 1; a second member of the group gets the message, judges once, 1 evaluation row, lag 0, one `evaluation.completed`, one `api_usage` row |
| `test_sigkill_after_commit_reproduces_without_a_second_judge_call` | SIGKILL after the DB commit, before producing: 1 evaluation row, `processed_events` row, lag 1, no output yet; the next member logs `REPRODUCE`, makes NO judge call, produces `evaluation.completed` (deterministic id), lag 0, still 1 row |
| `test_run_completed_is_emitted_once_with_evaluator_and_two_finalizers` | 3 calls of one run, each `call.completed` sent twice, evaluator + finalizer consumers: 3 evaluations, 3 judge calls, `test_runs` completed with summary, `run.completed` only ever with id `uuid5(run_id, "run.completed")` |
| `test_concurrent_finalizers_claim_the_run_once` | two finalizer members on the last two `evaluation.completed` events: exactly one `run.completed` message |

Unit tests: `backend/tests/unit/evaluation/test_worker_wiring.py` (registration with the framework, reproduce equals original outputs, error-to-disposition mapping, `get_client`, usage sink failure path).

### Live acceptance with the real model: `acceptance.txt` (script `acceptance.sh` + `acceptance.py`)
Compose project on real Kafka + Postgres; `migrate` (Alembic) and the seed CLI run in the image; `evaluator` (2 replicas) and `finalizer` containers from profile `workers`. One synthetic run with one call; `call.completed` published twice (same event id); ONE real DeepSeek call (`deepseek-v4-pro`, temp 0, 2230 in / 491 out tokens, $0.0049, `credit_use.md`).
- `evaluations` rows for the call: **1**; `rubric-2026-10-v1`, status `ok`, score 100, passed, prompt hash and model stored, tokens stored.
- `api_usage`: 1 row (`deepseek`, `llm_judge`, 2721 tokens, est_cost 0.0049, run id matches).
- `processed_events`: evaluator 1, finalizer 1. Worker log: the first delivery `processed`, the second `duplicate delivery; re-producing outputs` (no second HTTP request to DeepSeek).
- `evaluation.completed` and `run.completed` were each produced twice with ONE distinct event id (the re-produced duplicate); `run.completed` id equals `uuid5(run_id, "run.completed")`; `test_runs` = `completed`, `finished_at` set, `run_items` = `evaluated`, `dead_letters` = 0, consumer lag 0 for both groups.

## Honest limits
- The SIGKILL cases use a scripted judge (a crash test with the real model would double the spend); the real model is exercised once in the acceptance run, whose duplicate delivery is real.
- `expected_language`, `allowed_languages` and `expected_amounts` are not stored anywhere in the schema; the store derives them: language = `calls.language` (else persona), allowed = that plus `agents.languages`, amounts = numeric `*amount` keys of `scenarios.fixtures`. Expected tool calls come from `scenarios.expected_tool_calls`; tool calls are only loaded for glass-box agents.
- `ws_open_ms` is 0 (not stored), so first-greeting latency is relative to the first turn timeline.
- The finalizer also emits for `cancelled` runs (claim allows `status='cancelled'` while `finished_at IS NULL`); the every-minute reconciler and `evaluating` transitions remain API-03 / INFRA work.
- In the sandbox the evaluator container needs the proxy CA (`sandbox_override.yml`); normal environments do not.
- A first acceptance attempt failed before any request left the container (proxy CA missing), costing nothing; its log is not kept.
- The first full pytest run had 5 failures in INFRA-02 retry/DLQ tests (retry.30s / retry.5m / DLQ timing, none touching this task's code). The machine was shared with other agents' Kafka/pytest runs at the time and the extra handler calls in the failing assertions suggest foreign consumers on the default `localhost:9094`; this is a hypothesis, not proven. The same tests pass alone, and the whole suite passed on the rerun recorded in `pytest.txt`.
