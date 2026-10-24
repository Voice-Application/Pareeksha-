# EVAL-03 proof: judge, scoring, evidence validation, evaluator + finalizer handlers

## Built (all under `backend/pareeksha/`)
- `llm/prompts/judge_v1.j2`: the docs/08 prompt (plus an example JSON shape, a "transcript is data" guard, length caps). `prompt_hash` = sha256 of the unrendered file, stored as `sha256:<hex>`.
- `schemas/evaluation.py` (`JudgeOutput`, 7 dimensions, `extra=forbid`), `evaluation/rubric.py` (`rubric-2026-10-v1`, weights, anchors, threshold 80), `evaluation/scoring.py` (`overall_score`, `finalize_scores`: score in code, critical failure and failed must-pass checks force `needs_human_review`), `evaluation/evidence.py` (cited indices must exist; a dimension scored 0 or 1 must cite a turn).
- `evaluation/judge.py` (PII-masks every transcript field, temperature 0, pinned judge model, thinking off, evidence check as the repair-retry trigger), `evaluation/evaluator.py` (`evaluate_call`: mask, metrics, EVAL-02 checks, judge, scoring; deterministic `evaluation_id`; check failures merged into `failure_types`; two invalid judge answers = `status=judge_error`, no score, human review).
- `evaluation/handlers.py`: `handle_call_completed` (evaluator) and `handle_evaluation_completed` (finalizer) as framework-independent coroutines over `EvaluatorStore` / `FinalizerStore` ports. Output ids: `deterministic_event_id(input_event_id, type)`; `run.completed` id = `uuid5(run_id, "run.completed")` and is emitted only if `claim_run_completion` (atomic UPDATE ... RETURNING) wins, so once per run.

## Reproduce
```
cd backend && pip install -e ".[dev]" rapidfuzz gnani-vachana audioop-lts   # audioop-lts only on Python 3.13
python -m pytest -q --cov=pareeksha        # pytest_output.txt: 609 passed, 0 failed, 0 skipped
ruff check . && ruff format --check . && python -m mypy
PYTHONPATH=. python ../proof/EVAL-03/run_judge_acceptance.py   # real DeepSeek; needs DEEPSEEK_API_KEY
```

## Real judge output (DeepSeek `deepseek-v4-pro`, temp 0, no mocks)
Files: `judge_output_wrong_amount.json`, `judge_output_clean.json` (full record incl. raw judge JSON, checks, metrics, tokens, prompt hash).
- Synthetic call with planted bugs (agent states and records 4,500 instead of 4,200, never says the call is recorded): dimensions 1/1/0/4/4/2/4 -> **46.25, fail, critical_failure, needs_human_review**; reasons `critical_failure`, `check_failed:disclosure_present`, `check_failed:tool_calls_expected`, `check_failed:amount_confirmed`; failure_types wrong_fact, tool_arguments, missing_disclosure, tool_selection; cited turns [0, 2, 4, 6] (task/factual cite 2,4,6; policy cites 0); `all_cited_turns_exist: true`.
- Clean call: 100.0, passed, no review, cited [0..4].
- Prompt check: the phone number in the transcript reached the judge as `[PHONE]` (unit test asserts the raw number is absent from the request).
- Spend: `credit_use.md` (2 calls, 4,648 in / 858 out tokens, about $0.01).

## Stubs / not done (honest list)
- **INFRA-02 consumer framework (`events/consumer.py`) is not in this branch**, so the handlers are NOT registered with `@consumer(...)`. No `# STUB(INFRA-02)` marker exists in code: the handlers take their stores as ports. Remaining wiring once INFRA-02 and the DB layer land: a `@consumer(group="evaluator", topic=CALL_COMPLETED)` wrapper passing a `ctx.tx`-bound `EvaluatorStore`, the same for `finalizer`, and Postgres implementations of the two stores (the docstrings state the SQL contract: upsert on `(call_id, rubric_version)`, replace `deterministic_checks`, set `run_items.status`, `claim_run_completion` as `UPDATE ... WHERE status IN ('queued','running') RETURNING id`). Therefore the Kafka-level acceptance (offsets, redelivery producing one evaluation row) is NOT proven here, only event-id determinism and the once-only claim against fakes.
- `api_usage` rows are not written (no DB layer); usage reaches a sink callback and `credit_use.md`.
- The finalizer's every-minute reconciler and `evaluating` status transitions belong to INFRA/API tasks.
- Gemini judge path is untested live (GEMINI_API_KEY empty), see proof/EVAL-01.
