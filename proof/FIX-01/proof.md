# FIX-01 proof: P1 bugs from QA-03 (STATUS: done-unverified)

Branch `task/FIX-01` = `task/QA-03` + merges of `task/EVAL-04b`, `task/VOICE-06`, `task/DOC-02` (no conflicts).
Stack: private compose project `pk-f1` (Postgres :35432, Kafka :39094, API :38000), real Gnani + DeepSeek,
`sandbox_override.yml` (ports + proxy CA only). Web image not built (Docker Hub 429 on `node:22-alpine`); web served with `next start`.

| # | Bug | Fix | Evidence |
|---|---|---|---|
| a | `inbound_url` built from `PUBLIC_BASE_URL` (web app, 404) | `routers/integrations.py`: uses `PUBLIC_API_URL`, default `http://localhost:${API_HOST_PORT or API_PORT or 8000}`; `.env.example`, compose (`PUBLIC_API_URL`) and `docs/guides/04-webhook-source.md` updated | `test_inbound_url_ignores_the_web_app_base_url`, `pytest_integrations.txt` (32 passed) |
| b | integrations worker dead-lettered every event: `KeyError 'SECRET_KEY'` | `workers/integrations.py`: `_secret_box()` raises `SystemExit` with a clear message, called at startup before `run_worker`; compose passes `SECRET_KEY`; `.env.example` marks it REQUIRED. `make demo` (QA-05) generates one when empty | `tests/unit/test_integrations_worker_startup.py`; stack's `integrations` container starts with the generated key |
| c | `judge_error`: scores without cited turns still invalid after the single repair | `evaluation/evidence.py`: the repair message names the dimension, says to cite the turn where the problem happens (or where the agent should have acted), lists the agent turn indices, and forbids raising the score to avoid citing; `judge_v1.j2` states the rule as mandatory; `LLMClient.generate_json(repair_attempts=)`, judge uses 2 | `test_missing_evidence_message_says_how_to_fix...`, `test_scores_without_cited_turns_are_fixed_by_the_second_repair`, `test_two_repair_attempts_recover...` (no live reproduction: the failure is a rare model output) |
| d | bug 2 caught in 1 of 2 calls | see below | `results/`, `reevaluated.json` |

## (d) bug 2 root causes (two, found by running it)
1. `checks.check_amounts` returned `passed=None` whenever the agent had said the amount once (the greeting), so "never read the amount back before recording the promise" was invisible; the judge caught it only sometimes.
   Now: when the agent acted on an amount (a tool call with an `*amount*` argument) the amount must be stated again after the caller replied to its first statement (read-back); otherwise `amount_confirmed` fails (must-pass, cited turns). A statement counts if it is in the transcribed audio **or** in the text the agent reports it said (glass box). Calls with no such tool call are unaffected.
2. The **mock agent** lost its `record_promise_to_pay` tool call whenever the caller spoke over the reply (the reply task was cancelled before it sent the tool message): it happened to a *clean* call too (`results_before_mock_fix/clean-a.json`: 1 of 2 clean calls had no tool call). `mock_agent/server.py` now sends the tool message in a `finally` (test `test_tool_call_survives_the_caller_talking_over_the_reply`).

## Live results (same scenario/persona as QA-03: "Promise to pay on Friday", Priya, pstn_8k_alaw)
- Before (mock fix not in): bug 2 x2 -> neither flagged; clean x2 -> 1 had no tool call. (`results_before_mock_fix/`)
- After (`results/bug2-no_amount_confirm.json`, run `d03ca72b`): bug 2 **2 of 2 flagged**: `amount_confirmed` failed with cited turn 2 and `wrong_fact` (scores 77.5 and 60.0, one critical, none passed). Calls re-evaluated with the final check code (`reevaluated.json`).
- Clean x2 (`results/clean-a.json`, run `56b3d4ab`): 1 passed (95.0, no failed check). The other failed on `disclosure_present` (greeting audio cut: "this call is being") **and** the agent really never read the amount back (the caller asked "is that correct?" and the bot closed); the disclosure failure alone fails it, so the new rule did not turn a passing clean call into a failing one. Small n (2), honestly reported: clean calls with this caller are noisy.

Reproduce: `proof/FIX-01/run_bug2.sh` (needs the stack; bug container as in `proof/QA-03/start_bug_agents.sh`), `pytest backend/tests/evaluation backend/tests/unit/evaluation backend/tests/unit/llm`.

Also fixed: `web/lib/api/schema.d.ts` was stale against the merged API (found by the new QA-04 contract test) and regenerated.
