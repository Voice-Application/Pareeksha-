# EVAL-04 proof: `auditor` consumer, upload -> batch STT -> role detection -> judge

Branch `task/EVAL-04`, created from local `integrate/M2` (71a1022). Commit SHA: `git log -1 task/EVAL-04` (the commit contains this file).

## Built
- **`POST /audits`** (`api/routers/audits.py`, scope `audits:write`): multipart WAV/MP3, at most 10 MB (`413 file_too_large`), format sniffed from the bytes and decoded (`422 unsupported_audio`), `language` validated as `kn-IN` / `kn-IN,en-IN` (`400`), agent must belong to the key's project (`404`). In one transaction it inserts the `calls` row (`source=upload`, `status=transcribing`), stores the original in the blob store and writes `audit.requested` to the outbox. Returns `202 {call_id}`.
- **`auditor` consumer** (`workers/auditor.py` + `audit/pipeline.py`, INFRA-02 framework, group `auditor`, with a `reproduce` callback): load audio (blob, or SSRF-guarded download for imports, `audit/fetch.py`) -> decode to 16 kHz mono, stereo kept per channel (`audit/ingest.py`) -> **batch STT through the VOICE-07 provider abstraction** (`get_stt_provider()`, Gnani default) with diarization (2 speakers; 1 per channel when `stereo_channels_are_speakers`), **denoise**, and the agent's `bias_list` -> speaker labels `spk_0..` by first appearance -> **role detection** (`audit/roles.py`: first speaker is the agent, then an LLM check with `role_detect_v1.j2`; a confident LLM verdict wins and a disagreement is logged, low confidence or no LLM falls back to the first-speaker rule and says so) -> merged `turns` (+ PII-masked `text_masked`) -> `calls` completed (`speaker_map`, `duration_ms`, mixed WAV, `event_log`) -> `api_usage` rows -> `call.completed` (`source=upload|import`).
- **`POST /calls/{id}/speaker-map`**: rebuilds the turns from the stored diarized segments (`stt.json` next to the audio, no new STT spend), updates `speaker_map`, logs the override and queues a new `call.completed` through the outbox so the call is judged again.
- **`evaluator` consumer** (`workers/evaluator.py` + `evaluation/store.py`): EVAL-03 had only framework-independent handlers; this wires `handle_call_completed` to the framework with a Postgres store (snapshot for uploads and simulations, evaluation upsert on `(call, rubric version)`, deterministic checks, `call_metrics`, `api_usage`, run item status). Without it an audit could not be judged ("same rubric", re-evaluate on swap). `reproduce` re-emits the stored result on duplicate delivery.
- Failure handling: unusable recording (corrupt, no speech, vendor 4xx, unsafe URL) -> `calls.status=error` with the reason, no retry; transient (STT 5xx/429, download errors, LLM 5xx) -> `RetryableError`, and on the last attempt the call is marked `error` instead of hanging in `transcribing`; operator problems (no `GNANI_API_KEY`, provider without diarization) -> `PermanentError` -> DLQ.
- Support: `storage/blob.py` (`BlobStore`, `LocalBlobStore` under `DATA_DIR`), `events/outbox.enqueue_session` (outbox write from an API SQLAlchemy session), prompt `role_detect_v1.j2`, `soundfile` declared as a dependency (decodes WAV and MP3, no ffmpeg).
- **STUBs removed:** both `STUB(EVAL-04)` handlers (`POST /audits`, `POST /calls/{id}/speaker-map`). No `STUB(EVAL-04)` remains.
- **Contract change (additive, flagged as ISSUE):** `STTProvider.transcribe(..., denoise=False)` and `STTCapabilities.denoise`; Gnani passes it to the batch job, the other four providers refuse it. See `CHANGELOG.md`, `docs/contracts.md` section 4.

## Acceptance criteria (docs/SCOPE.md EVAL-04, FR-AU-1..4)
| Criterion | Evidence |
|---|---|
| FR-AU-1 WAV/MP3 <= 10 MB stored, `source=upload`; > 10 MB rejected | `tests/integration/test_audit_upload.py` (WAV, MP3, exactly 10 MB accepted, +1 byte -> 413, non-audio/corrupt/empty -> 422, 404/400/401/403) |
| FR-AU-2 diarized turns with speaker labels | real run below; `tests/integration/test_audit_pipeline.py` (scripted STT) |
| FR-AU-3 speaker role assigned; swap re-runs evaluation | `tests/integration/test_agent_role_swap.py`; real run below |
| FR-AU-4 same rubric version | `tests/integration/test_audit_same_rubric.py` (upload and simulation: same `rubric_version_id`, `prompt_hash`, judge model, temperature, identical rubric anchors in the prompt) |
| diarize + denoise + bias words sent to STT | `test_audit_pipeline.py::test_upload_becomes_labelled_turns_and_call_completed` asserts `diarize=True, num_speakers=2, denoise=True, bias_words`; real run |
| `call.completed` emitted | same test; real run |

## Real-key acceptance (Gnani + DeepSeek, one synthetic recording)
Command: `cd backend && PYTHONPATH=. python ../proof/EVAL-04/run_acceptance.py ../proof/EVAL-04` (needs `GNANI_API_KEY`, `DEEPSEEK_API_KEY`, a Postgres server). Output: `acceptance_run.log`, `acceptance_result.json`, `synthetic_call.wav` (17.5 s, hi-IN, invented lender "Shakti Finance", voices Shivani + Shubham, no human voice), `blobs/.../stt.json`, `usage.jsonl`, `credit_use.md`.

What happened (no mocks: real TTS to build the call, real HTTP API, real Postgres + seeded rubric/agent, real Gnani batch STT, real DeepSeek):
1. `POST /audits` -> `202`. Auditor -> Gnani returned 3 segments with speakers `1, 2, 1` at 0-10.08 s, 10.08-13.82 s, 13.82-17.44 s: exactly the three scripted turns. The recording-disclosure sentence and "EMI of 4200" were transcribed.
2. Role check (DeepSeek v4-pro): `spk_0 = agent, spk_1 = caller`, confidence high, agrees with the first-speaker rule. Turns stored: agent / caller / agent. `calls.status=completed`, `end_reason=upload`.
3. Judge (same `evaluator` code as simulations): rubric `rubric-2026-10-v1`, score 100.0, passed, no review; checks: disclosure present, no forbidden phrase, language match hi-IN, no loop.
4. `POST /calls/{id}/speaker-map` with the roles swapped -> `202`; turns rebuilt (caller / agent / caller), a new `call.completed` queued, judged again: still **one** evaluation row, now score 82.5, failed, `needs_human_review`, `check_failed:disclosure_present`, `missing_disclosure` (the recording sentence now belongs to the "caller"). Re-evaluation visibly changed the verdict.
5. `api_usage` has the STT row (17.46 s) and three LLM rows (role check, two judgments).
6. Real-API finding fixed during the run: Gnani batch rejects `bias_list` entries that are phrases (`400 INVALID_CONFIG: bias_list entries must be single words`); the auditor now splits entries into single words (`bias_words()`, unit-tested). First attempt log: `acceptance_run_1_bias_phrase_400.log` (the call was correctly marked `error`, nothing hung).

Not exercised in the real run: Kafka (the consumer framework is covered by INFRA-02's integration tests and by the full suite below; this run calls the registered handlers in a transaction like the framework's), MP3 and stereo against the real vendor (covered with scripted STT), the import path against a real telephony host.

## Reproduce tests
```
cd backend
INFRA_TEST_KAFKA_BOOTSTRAP=localhost:<private broker> python3 -m pytest tests -q --cov --cov-report=term   # 921 passed, 0 failed, 0 skipped, coverage 98%
ruff check . && ruff format --check . && python3 -m mypy                                                  # clean (strict)
```
Logs: `pytest_full.txt`, `lint_types.txt`. New modules: `audit/pipeline.py` 99%, `audit/turns.py` 99%, `audit/ingest.py`, `audit/roles.py`, `audit/fetch.py`, `storage/blob.py`, `evaluation/store.py` 100%; `workers/auditor.py` 92%, `workers/evaluator.py` 89% (the `main()` entry points).

Environment note: the host shares one Kafka between several agents' stacks, so INFRA-02's retry/redelivery tests (`test_retryable_failure_then_success_processes_once`, `test_retrier_pauses_until_not_before...`, `test_real_delays`) fail there on the unmodified `integrate/M2` too (two retriers consume `retry.30s`). The numbers above are from a private single-node Kafka (`apache/kafka:4.0.0`, created from `infra/kafka/create-topics.sh`), where the whole suite passes.

## Not done / issues
- Per-agent / per-run STT provider override (`SpeechSelection`) is not wired: the auditor uses `STT_PROVIDER` (agent/run schemas are frozen).
- A low-confidence or disagreeing role verdict is recorded in `calls.event_log` but does not yet set `needs_human_review` on the evaluation (that flag belongs to EVAL-03's scoring).
- Imported calls need INT-03 to create the `calls` row and `external_refs` (the auditor expects the row, downloads `recording_ref`, stores it under `imports/`).
- The `finalizer` worker is still unwired (EVAL-03 scope; uploads have no run so it is a no-op for them).
