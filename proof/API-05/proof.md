# API-05 proof: regression promote + suite runs, calibration, review / re-evaluate, scenario generation

Branch `task/API-05` from `integrate/M2` @ 71a1022. Commit SHA: the last commit of `git log task/API-05`. `docs/contracts.md`, `events/schemas.py`, `topics.py` and every request/response model are untouched. Dependency EVAL-03 is on `integrate/M2`.

## The 9 `STUB(API-05)` handlers, replaced

| Route | Behaviour |
|---|---|
| `POST /calls/{id}/promote` | Creates a `promoted` scenario (`source_call_id` = the call) and a regression test (status, failure type, baseline default 80, tolerance 5, persona + noise profile of the original run item). Simulated call: copy of its scenario with the judge summary and notes appended to the success criteria. Upload / import call: goal from the first caller turns (PII-masked text), criteria from summary + notes, no persona. Idempotent per (call, failure type). Call without an agent: 400. |
| `POST /runs:regression` | Selects the agent's tests with the requested statuses (default `blocking`), snapshots the agent (no secrets), writes `test_runs(kind=regression, queued)` and a `run.requested` outbox event (`regression_statuses`) in one transaction; returns `{id, status, item_count, estimate}`. 404 unknown agent, 409 no matching tests, 402 + estimate when above `BUDGET_CREDITS` minus recorded spend (override: `confirm_over_budget`). |
| `GET /regression-tests`, `PATCH /regression-tests/{id}` | Filters `agent_id`, `status`; `last_run_id`, `last_score`, `last_passed` from the newest evaluated run item judged against the test's own baseline - tolerance and critical flag; patch status / baseline / tolerance / notes (null = unchanged). |
| `GET /calibration` | One human label per evaluation (newest review) vs the judge: Cohen's kappa on pass/fail, Spearman on overall score (average ranks for ties), mean absolute error per rubric dimension. Default: the active rubric; `rubric_version` filter; project-scoped. Undefined values are `null`. |
| `POST /calls/{id}/review` | Stores per-dimension human scores (0-4, known keys only) on the call's newest `ok` evaluation; `overall_score` computed in code only when all 7 dimensions are given; one review per reviewer and evaluation (409); no evaluation yet: 409. |
| `POST /calls/{id}/reevaluate` | Enqueues a fresh `call.completed` (new event id) from the call's run item; only the build's rubric (`rubric-2026-10-v1`) is accepted (unknown version 404, other known version 400: `CallCompleted` carries no rubric field); call not `completed`: 409. |
| `POST /agents/{id}/scenarios:generate`, `GET /scenario-drafts/{id}` | Validates count and mix (sum = count, keys `happy_path` / `edge_case` / `adversarial`), writes `scenario_drafts(pending)` + `scenario.generate.requested` in one transaction (202). The new `generator` consumer asks the LLM (DeepSeek default, `SCENARIO_GEN` temperature 0.8) in batches of about 10, checks count, mix, unique titles, declared tools and the `ScenarioCreate` schema (one repair retry), and stores `ready` drafts or `failed` + reason. Drafts are never saved as scenarios; `POST /scenarios:bulk` saves the reviewed ones. |

Suite verdict (FR-RG-2): `regression/verdict.py` (`score >= baseline - tolerance`, no critical failure, default tolerance 5). `evaluation/handlers.py::summarize_run` now uses it for regression runs (`RunItemOutcome.baseline_score` / `tolerance`), so `run.completed.summary.suite_passed` is false if any blocking test fails; `regression/outcomes.py::run_outcomes` builds those outcomes from the database for the finalizer's store.

New modules: `regression/{verdict,outcomes,promote,estimate}.py`, `evaluation/calibration.py`, `scenario_gen/generator.py`, `llm/prompts/scenario_gen_v1.j2`, `workers/generator.py` (`python -m pareeksha.workers.generator`, the compose service already exists), `api/outbox.py` (identical to the EVAL-05 branch's file), `db/queries.py` (`distinct_on`, SQLAlchemy 2.0/2.1 compatible).

Decisions and caveats
- The run cost estimate (`regression/estimate.py`) is a documented heuristic from `max_turns` and the `COST_*` rates (unset rate = 0). API-03 owns the matrix-run estimate and may replace it; the shapes match `RunEstimate`.
- `409` was added to the documented responses of `POST /runs:regression` (no tests to run).
- The finalizer / evaluator consumers and their SQL stores are not in `integrate/M2` (EVAL-03 delivered framework-independent handlers), so `suite_passed` reaches `test_runs.summary` only once that wiring exists; this task provides the verdict function, the DB read side and tests for both.
- Re-evaluation with a second rubric version needs a new rubric in code plus a rubric field on the event (contract change): reported, not done.

## Reproduce

```
docker compose up -d kafka postgres && docker compose up kafka-init
pip install -r requirements.txt -r backend/requirements-dev.txt
cd backend && python3 -m pytest -p no:cacheprovider --cov=pareeksha -rs      # pytest.txt
ruff check . && ruff format --check . && python3 -m mypy                     # lint.txt
cd .. && INFRA_TEST_KAFKA_BOOTSTRAP=localhost:9094 PG=postgresql://pareeksha:pareeksha@localhost:5432 \
   python3 proof/API-05/live_run.py                                          # needs DEEPSEEK_API_KEY
```

## Results

### Tests
`879 passed, 0 failed, 0 skipped` (8 min 52 s, includes INFRA-02's real 30 s / 5 min delay test; Kafka + Postgres real), total coverage **97 %** (new modules 95-100 %; the uncovered lines are worker `main()` / start-up wiring and one unreachable defensive branch). `ruff check`, `ruff format --check` and `mypy` (strict) clean (`lint.txt`).

Map to TEST_PLAN: `tests/unit/test_calibration.py` (T-FR-EV-8, kappa 0.4 and Spearman 0.9487 hand-computed, scipy cross-check), `tests/unit/test_regression_verdict.py`, `tests/integration/test_promote_to_regression.py` (T-FR-AU-5), `test_scenario_source.py` (T-FR-SC-4), `test_regression_fields.py` (T-FR-RG-1), `test_regression_suite.py` (T-FR-RG-2: run creation, outbox event, 402 / 409 / 404, verdict from real rows incl. critical and errored items), `test_human_review.py` (T-FR-EV-7, `/calibration` against hand-computed kappa 0.5 / Spearman 1.0 / MAE 0.5, re-evaluation), `test_scenario_generation.py` (API -> outbox -> real handler on Postgres -> poll; failure and retry paths) and `tests/judge/test_scenario_generator.py` (T-FR-SC-2 with scripted answers; the live DeepSeek run is below). The model is scripted in tests; Postgres is real.

### Live run (`live_run.txt`, `live_result.json`, `scenario_drafts.json`, `*.log`)
Real Kafka, Postgres, uvicorn API over HTTP, outbox relay and `generator` process, real DeepSeek:
- Generation: `POST scenarios:generate` count 10, mix 3 / 4 / 3 -> `ready` after 16 s, 10 drafts, all valid `ScenarioCreate`, mix 3 / 4 / 3 exactly, 10 unique titles, 1 LLM call, no repair, 3,477 tokens (`credit_use.md`).
- Promote: failed call (score 41) -> promoted scenario `source=promoted`, `source_call_id` = the call; regression test blocking, baseline 80, tolerance 5, persona and noise profile carried over.
- `POST /runs:regression` -> `item_count 1`; the `run.requested` message (kind regression, `regression_statuses ["blocking"]`) was read back from the Kafka topic after the relay published it.
- Suite verdict from database rows: score 76 vs baseline 80 / tolerance 5 -> `suite_passed true`; score 74 -> `false`; the list endpoint then shows `last_score 74`, `last_passed false`.
- 4 human reviews -> `GET /calibration`: `n 4, kappa_pass_fail 0.5, spearman_overall 1.0`, every dimension MAE 0.5 (the same numbers as the hand computation in the test).
- Calls were seeded into the tables (the simulator and evaluator workers belong to other tasks); the real kappa on real labels is EVAL-06.

## Not covered / follow-ups
- Finalizer / evaluator consumer wiring (see caveat). Run compare, SSE, DLQ endpoints are API-04.
- FR-RG-4 (CLI exit code) is INT-04; FE pages are FE-04 / FE-05.
