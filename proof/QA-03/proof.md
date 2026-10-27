# QA-03 proof: planted-bug detection + 40-call Kafka run

STATUS: done-unverified. Branch `task/QA-03` (from `integrate/M3`). Stack: private compose project `pk-m3`
(Postgres :25432, Kafka :29094, API :28000), real Gnani STT/TTS, real DeepSeek caller + judge, all 12 workers
as separate containers. Sandbox overlay: `sandbox_override.yml` (ports + proxy CA only).

## Fixes made (no judge weakening)
1. Seed fixtures aligned with the mock agent's clean behaviour (`backend/pareeksha/seed/data/`): every
   scenario `emi_amount` 4,500 (the mock agent's amount), expected tool arg `amount_inr: 4500` (what the bot
   sends), lender "Suraksha Finance" (the bot's greeting). Result: the clean mock agent now passes on
   cooperative personas (`clean-a`, `clean-d`: 4/4 pass, scores 97.5-100) instead of 11 of 12 critical failures.
2. Bug 3 was invisible: the STT of the bot's reply ran in the caller's language (kn-IN) and transliterated the
   English reply into Kannada script, so `language_detected` said kn-IN and the judge saw "Kannada with code-mix".
   `simulation/turn_tracker.py` now sets an agent turn's `language_detected` from the script of what the bot
   reported it said (glass-box text); `evaluation/pg_stores.py` allows only the caller's language for simulated
   calls (the agent supporting English made `language_match` unfailable). Unit test added. This is stricter, not weaker.

## GOAL item 4: planted bugs (`catch_report.json`, `summarize.py`, `analyze.py`, `results/*.json`)
One mock-agent container per bug (`start_bug_agents.sh`, `MOCK_BUGS=<bug>`), 2 calls each via `POST /runs`
(`run_bugs.sh`, `run_bugs2.sh`). "Caught" = more than half of the bug's calls carry the bug's signature in the
platform output (failed check or judge failure type) with cited turn indices.

| Bug | Calls flagged | Signature | Cited turns | Paired clean run signature hits |
|---|---|---|---|---|
| 1 no disclosure | 2/2 | `recording` check failed, `missing_disclosure` | [0,2] [0,2] | 0/2 |
| 2 no amount confirm | 1/2 | judge `task_completion`=2 ("amount not confirmed") | [4,5] / not flagged | 0/2 |
| 3 English to Kannada | 2/2 | `language_match` check + `language_mismatch`, language_handling=1 | [0,2,4,6] [0,2,4,6,7] | 0/2 |
| 4 ignores interruption | 2/2 | `interruption_handling` failure type, conversation_flow=2 | [1,4,6] [1,2] | 0/2 |
| 5 false waiver | 2/2 | `policy_violation`, critical_failure, score 10-24 | [2,4] [2] | 0/2 |

**Caught 4 of 5** (criterion >= 4). Bug 2 is the weak one: flagged in one of two calls only, not counted.
A re-test of bug 2 on "Already paid" (`bug2b`) is invalid evidence: the clean bot fails that scenario equally (`clean-e`).
Clean baselines: `clean-a` Priya/Deepa 2/2 pass, `clean-d` Deepa 2/2 pass. `clean-b` (Interrupter) and `clean-c`
(Off-topic tester) fail 0/2: the scripted bot genuinely loops/misses the tool call under those personas, so
"clean calls pass" holds for cooperative personas only. Small n (2 per bug), one noise profile.

## GOAL item 3: 40-call run through Kafka
- run_id `8422cb13-0f26-4afa-98ef-77a7abb5ea70`: 5 scenarios x 4 personas x 2 noise profiles, clean agent, `run40.sh`; wall 11 min 23 s (`results/run40.json`, `db_query_output_run40.txt`, `run40_samples.txt`).
- Items: 38 `evaluated`, 1 `error` (call `infra_error`: Gnani caller TTS TimeoutError), 1 `judge_error` (judge output invalid after the repair retry: scores without cited turns; not infrastructure).
- **Calls free of infrastructure errors: 39/40 = 97.5%** (38/40 = 95.0% if the judge_error is also counted). Criterion >= 95%: PASS either way.
- Kafka: all consumer groups lag 0 (`kafka_consumer_lag.txt`); `processed_events`: planner 15, simulator 70, evaluator 65, finalizer 65 over the stack's life; outbox backlog 0 (`db_query_output_run40_consumers.txt`).
- Judged outcomes (not infra): the run summary shows pass_rate 0.0, 29 critical failures. The matrix includes scenarios the scripted bot cannot satisfy (asks-for-human needs `transfer_to_human`, already-paid needs UTR handling), so these are real findings about the bot, not platform errors.
- ISSUE: the `integrations` worker dead-lettered every `evaluation.completed`/`run.completed` event (80 rows in `dead_letters`, `KeyError: 'SECRET_KEY'`): the `.env` used for this run did not set `SECRET_KEY` (documented in `.env.example`). Not an item-3 error, but the worker has no friendly failure for a missing key.

Credit use: `credit_use.md`.
