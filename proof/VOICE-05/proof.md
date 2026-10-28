# VOICE-05 proof — `simulator` consumer, 12-call run end to end

STATUS: done-unverified. Branch `task/VOICE-05` (from `task/VOICE-04`).

## What was built
- `backend/pareeksha/workers/simulator.py`: consumer group `simulator` on `call.requested`.
  1. `start_item` (API-03) takes the run's slot and marks the item `connecting` on its own autocommit connection (visible to the other simulators at once). At the cap it raises `Throttled` (retry.30s, attempt unchanged); cancelled/finished items are skipped; a redelivery of an item that holds its slot resumes it.
  2. Reads agent / scenario / persona / noise profile rows (`simulation/store.py`), creates the `calls` row (`in_progress`), runs the VOICE-04 `CallRunner` outside any transaction (real Gnani STT/TTS, DeepSeek caller, `max_poll_interval_ms` 40 min).
  3. Recordings to the blob store; in the framework transaction: call row finished, turns (PII-masked copy), tool calls, STT/TTS usage, item `completed` and `release_slot`, all committed with the `processed_events` row; `call.completed` produced for the evaluator.
  4. Duplicate delivery: `reproduce` re-emits the same `call.completed` without calling the agent. `connect_failed` / `infra_error` / a crashing pipeline: call saved with status `error`, item `error`, slot freed, nothing sent to the evaluator.
- `backend/pareeksha/simulation/store.py`: the SQL side. Call ids are `uuid5(run_item_id)` so a crash + redelivery reuses the row.
- Gnani 429 handling (`gnani/clients.py`): "only 1 active request per key" collided constantly with 3 simulators + the mock agent (first real attempt: 1 of 12 calls died with `infra_error`). `_retry` now retries 429 up to 25 times with jittered 0.2-3 s waits, other failures still 3 times (unit test).
- Dockerfile / `pyproject.toml`: `pipecat-ai[silero]` added (image builds; `import pareeksha.workers.simulator` works in it).
- Tests: `tests/integration/test_simulator_worker.py` (6, real Postgres: save + slot release + event, throttle at cap, cancelled skip, failed call, crashing pipeline, redelivery + duplicate), `tests/unit/gnani` rate-limit test.

## Real end-to-end run (all workers as separate processes, real Kafka 4.0 + Postgres 16 in a private compose project `pk-m2b`, ports 19094/15432)
Processes: API, outbox-relay, planner, 3x simulator, evaluator, finalizer, reconciler, retrier, dlq-recorder, mock agent (clean). Reproduce: `start_run.py` (creates the run through `POST /api/v1/runs`), `watch_run.sh` (samples the DB every 3 s).

- run_id `0141c63b-794e-4eea-9516-3c273a21aed1` (`run.json`): 2 scenarios x 2 personas x 1 profile (`pstn_8k_alaw`) x 3 repeats = 12 items, `config.max_concurrency` 3.
- Result: status `completed`, 12 of 12 items `evaluated`, 0 error, 0 dead letters, outbox fully published; wall time 5 min 32 s.
- Cap: `slot_samples.txt` (every 3 s) never shows `active_calls` above 3 (max 3), ends at 0.
- call_ids and per-call data: `db_query_output.txt` (12 calls, all `agent_hangup`, 5-8 turns, audio present, evaluation row each); evaluation JSON per call in `evaluations/<call_id>.json`; usage in the same file.
- Kafka: `kafka_consumer_lag.txt` — every group at lag 0, `processed_events`: planner 1, simulator 12, evaluator 12, finalizer 12 (exactly once each).
- Sample call: `sample_call_turns.txt` and `audio/3841556b_{caller,agent,mixed}.wav`; simulator logs `simulator{1,2,3}.log`.
- Infra-error rate: 0 of 12 (criterion >= 95%).
- Throttle path (run at the cap) was not hit live (3 simulators = cap 3); it is covered by `test_at_the_cap_the_message_is_throttled...` and API-03's Kafka test.

## Issues found (for the owners)
1. The judge scores the CLEAN mock agent as failing (11 of 12 `critical_failure`, "misstated EMI amount 4500 instead of 6500"): the mock agent's script is fixed (4,500) while seed scenario fixtures use other amounts. QA-03 needs matching fixtures or a per-scenario amount before bug-vs-clean comparison means anything. Not changed here (VOICE-03/EVAL-03 scope).
2. `GET /calls/{id}` is still `not_implemented` (API-04), so evaluation JSON was exported from Postgres.
3. Gnani's one-request-at-a-time limit makes call duration (~55-80 s) dominated by queueing at 3 simulators; more instances will not scale until the key allows more concurrency.

## Tests
`pytest_full.txt`: full backend suite, 1101 collected: 1097 passed, 4 failed because my live e2e stack (retrier/dlq-recorder workers) was still consuming the same private broker. With the stack stopped, those 4 files (`test_consumer_framework`, `test_retrier_and_recorder`, `test_real_delays`: 12 tests) pass: 12 passed. Net: 0 failed, 0 skipped. `ruff check`, `ruff format --check`, `python3 -m mypy` clean.
