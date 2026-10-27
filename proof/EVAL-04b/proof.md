# EVAL-04b proof — role-detection review flag + per-agent speech override

STATUS: done-unverified. Branch `task/EVAL-04b` from `integrate/M2b` (eca23f5).

## What changed
- `audit/roles.py: role_review_reasons(event_log)` reads the `role_detection` entry of `calls.event_log`: `llm_confidence == "low"` -> `role_detection_low_confidence`; `agrees_with_heuristic is False` -> `role_detection_disagreement`. No LLM verdict (not configured / unusable) adds nothing.
- `PgEvaluatorStore.load_snapshot` loads `calls.event_log` into `CallSnapshot.review_reasons`; `evaluate_call` merges them into `review_reasons` and sets `needs_human_review` (also on the `judge_error` path). Simulated calls have no entry, so they are unaffected.
- Per-agent speech provider: `agents.adapter_config["speech"] = {"stt": ..., "tts": ...}` (the frozen agent schema has no field). `speech/agent_config.py: speech_selection()` -> `SpeechSelection`; `AgentCreate`/`AgentUpdate` reject unknown providers/extra keys (`400`); the auditor loads `a.adapter_config` and calls `stt_factory(selection=...)` only when an override exists (invalid stored value -> `PermanentError`/DLQ). The TTS half is read by the same helper for the simulator, which is not in this branch's base. Documented as additive in `docs/contracts.md` §4.1/§4.2 and CHANGELOG.

## Real run (real Gnani batch STT + DeepSeek role check and judge; keys from env, never printed)
```
PYTHONPATH=backend python scripts/audit_role_review_demo.py --out proof/EVAL-04b/run.json \
  pipecat_mixed.wav trimmed_caller_first.wav
```
`pipecat_mixed.wav` = the VOICE-06 real call (`task/VOICE-06:proof/VOICE-06/calls/00_pipecat_clean/mixed.wav`, synthetic voices); `trimmed_caller_first.wav` = the same file from 21 s to 70 s, so the customer speaks first.
| recording | roles | LLM confidence | agrees with first-speaker rule | result |
|---|---|---|---|---|
| pipecat_mixed (100 s) | agent, caller | high | yes | score 70.0, `needs_human_review` false, `review_reasons` [] |
| trimmed_caller_first (49 s) | caller, agent (LLM overrides) | high | **no** | score 63.75, `needs_human_review` **true**, `review_reasons` [`role_detection_disagreement`] |
Full output: `run.json`. A real `low`-confidence verdict did not occur; that branch is covered by scripted tests only.

## Tests
- `tests/unit/audit/test_role_review.py` (18): reason extraction table, forced review on an otherwise passing call, reasons kept on `judge_error`, speech override parsing/validation, schema validation.
- `tests/integration/test_audit_role_review.py` (6, Postgres): audit -> judge -> `evaluations.needs_human_review` / `review_reasons` for agree / low / disagree; override reaches `stt_factory`; no override passes none; invalid stored override is a dead letter.
- Full backend suite + coverage: `pytest_full.txt`. `ruff check`, `ruff format --check`, `python3 -m mypy` in `backend/`: clean (`lint_types.txt`).
