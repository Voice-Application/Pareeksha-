# Contracts for approval (TL-01)

Frozen as code on 23 Oct 2026 for the Day 1 checkpoint. After approval, any change needs Tech Lead sign-off and a `CHANGELOG.md` entry. Source of truth is the code named in each heading; this page is the summary. Reproduce everything with `cd backend && python -m pytest && ruff check . && python -m mypy`.

## 1. Kafka topics (`backend/pareeksha/events/topics.py`)

12 topics, all `pareeksha.<name>.v1`. Work topics 6 partitions, others 3; retention 7 days (progress 1 day, DLQ 30 days). A test checks this module against `03-TRD.md` section 10.2 and `create-topics.sh`.

| Topic | Key | Producer to consumer group |
|---|---|---|
| `run.requested` | run_id | api (outbox) to planner |
| `call.requested` | **run_item_id** | planner / regression to simulator |
| `audit.requested` | call_id | api / source connectors to auditor |
| `call.completed` | call_id | simulator, auditor to evaluator |
| `evaluation.completed` | call_id | evaluator to finalizer, integrations |
| `run.completed` | run_id | finalizer to integrations |
| `progress` | run_id or call_id | all workers to API SSE |
| `scenario.generate.requested` | agent_id | api to generator |
| `dialect.clip.requested` | sample_id | api to dialect |
| `retry.30s`, `retry.5m`, `dlq` | original key | any consumer to retrier / dlq-recorder |

Rules encoded: max 3 attempts (attempt 2 uses retry.30s, attempt 3 retry.5m, then DLQ); headers `x-target-topic`, `x-not-before`, `x-error`, `x-reason` (`throttled` does not consume an attempt); output event id = `uuid5(input_event_id, output_type)`.

## 2. Events (`backend/pareeksha/events/schemas.py`)

Envelope: `event_id, type, version, occurred_at (UTC), correlation_id, causation_id, attempt, producer, payload`. Unknown fields are rejected; `type` must match the payload class. Payloads carry IDs and small facts only.

| Event type | Key fields |
|---|---|
| `run.requested` | run_id, agent_id, kind, scenario_ids, persona_ids, noise_profile_ids, repeats, seed, regression_statuses |
| `call.requested` | run_id, run_item_id, agent_id, scenario_id, persona_id, noise_profile_id, seed, regression_test_id? |
| `audit.requested` | call_id, source (upload/import), agent_id?, language, recording_ref, integration_id?, external_id? |
| `call.completed` | call_id, source, agent_id?, run_id?, run_item_id?, end_reason? |
| `evaluation.completed` | call_id, evaluation_id, status, overall_score?, passed?, critical_failure, needs_human_review, failure_types |
| `run.completed` | run_id, agent_id, kind, status, summary (counts, pass_rate, critical_failures, score_mean, suite_passed?) |
| `progress` | kind (`item.status`, `call.evaluated`, `run.completed`), run_id?, call_id?, plus the SSE fields of that kind |
| `scenario.generate.requested` | draft_id, agent_id, count, mix |
| `dialect.clip.requested` | report_id, dataset_id, sample_id, noise_profile_id, engines, expected_results |

`GET /api/v1/events/schemas` serves the JSON Schemas (implemented, not a stub).

## 3. REST API (`GET /openapi.json`, code in `backend/pareeksha/api/`)

76 operations under `/api/v1`: the 68 of `06-api-spec.md` sections 1 to 11 plus 7 data-gap additions and `GET /speech/providers` (section 12 there). Typed request/response models, status codes, `ApiKey` bearer security with a scope per operation, error envelope `{error:{code,message,details}}`, validation failures `400` (not 422), pagination `{items,next_cursor}`, stable operationIds. Three routes are real (`GET /health`, `GET /events/schemas`, `GET /speech/providers`); the other 73 return `501 not_implemented` with the owner task in `error.details.owner`, each marked `# STUB(<task>)` in its handler.

Scope per operation (**decision for approval**, the spec lists scopes but not the mapping): `read` for all GETs, previews and `runs:estimate`; `runs:write` for creating/changing agents, scenarios, personas, noise profiles, runs, reviews, promotion, regression tests, dialect datasets (so `pareeksha apply` and the GitHub Action work with a `read`+`runs:write` key); `audits:write` for `POST /audits` and speaker-map; `admin` for integrations, DLQ replay/discard and API keys. `admin` implies all.

| Area | Routes |
|---|---|
| Agents | CRUD (no delete: archive), `/agents/{id}/archive`, `/agents/{id}/test-connection` |
| Scenarios, personas, noise profiles | CRUD, `/scenarios:bulk`, `/agents/{id}/scenarios:generate`, `/scenario-drafts/{id}`, `/personas/{id}/preview`, `/noise-profiles/{id}/preview` |
| Runs | `POST/GET /runs`, `/runs:estimate`, `/runs:regression`, `/runs/{id}` (+`/items`, `/events` SSE, `/cancel`, `/report`), `/runs/compare` |
| Calls and audits | `GET /calls`, `/calls/{id}` (+`/audio/{track}`, `/reevaluate`, `/review`, `/promote`, `/speaker-map`), `POST /audits` |
| Regression | `GET /regression-tests`, `PATCH /regression-tests/{id}` |
| Dialect | `/dialect-datasets` (+`/samples`, `/evaluate`), `/dialect-reports` (+`/{id}`, `/clips`, `/html`) |
| Integrations | `/integrations` CRUD, `/connectors`, `/{id}/test`, `/{id}/deliveries`, `/redeliver`; `POST /webhooks/inbound/{id}` (HMAC, no key) |
| Ops | `GET /health` (also `/health` unprefixed for Compose), `/calibration`, `/usage`, `/metrics/summary`, `/dlq` (+replay, discard), `/api-keys`, `/events/schemas` |

Stub owners: API-02 (31), API-04 (11), API-05 (9), EVAL-05 (8), API-03 (6), INT-01 (4), EVAL-04 (2), INT-03 (1), VOICE-04 (1). Assignments not obvious from AGENTS section 7: previews to API-02, test-connection to VOICE-04, speaker-map and `POST /audits` to EVAL-04, run report/compare/SSE and call reads to API-04, regression and calibration endpoints to API-05, connector list/test/deliveries to INT-01. API-01 owns the key check inside `api/auth.py`.

**Added to close design data gaps** (G-numbers from `docs/design/pages/00-shared.md` section 11, each backed by an FR): G-1 run list filters (FR-DB-1), G-2/G-10/G-13 `GET /calls` with `source`, `needs_review`, `reviewed` filters (FR-AU-*, FR-EV-7, FR-EV-8), G-3 `POST /runs:estimate` (FR-RN-2), G-7 partly via `RunSummary.score_distribution` (FR-DB-2), G-9 partly via `run_id` on calls, G-11 dialect lists plus `/clips` drill-down (FR-DI-1, FR-DI-4, FR-DB-4), G-12 regression list and patch (FR-RG-1).

**Not in v1** (no requirement behind them; pages degrade as DES describes): G-4 last test-connection result on the agent object; G-5 usage counts on scenarios (delete already returns 409 when referenced); G-6 previews with unsaved values (FR-PE-3 previews a saved persona); G-8 agent snapshot on `GET /runs/{id}`; G-9 scenario/persona/profile titles on the call object; G-7 per-item failure tag, latency and flag (FR-DB-2 needs run-level figures only); deleting regression tests (use status `retired`).

## 4. Interfaces

- **Connector** (`integrations/base.py`, entry-point group `pareeksha.connectors`): ABC with `name`, `direction` (source/sink/both), `config_schema`, `secrets_schema`, `subscribes_to`; `async test`, sink `async handle(event, config, secrets, ctx) -> DeliveryOutcome`, source `async ingest(request, config, secrets) -> list[AuditRequest]`. Sinks get an `EvaluationSummary` with no transcript. `validate_connector_class` is what the registry runs on every plugin.
- **Agent adapter** (`adapters/base.py`): `Adapter.connect(agent, call_ctx) -> AudioSession`; `AudioSession` has `send_pcm16(frame)`, `receive()` (async iterator of `AgentAudio`, `AgentTranscript`, `AgentToolCall`, `AgentCallEnd`), `close()`, and works as `async with`. The `pareeksha-audio-v1` JSON messages (`start`, `stop`, `transcript`, `tool_call`, `call_end`) are typed here; audio is PCM s16le mono 16 kHz, 20 ms frames (640 bytes).
- **LLM provider** (`llm/base.py`, `llm/config.py`; owner-approved change): `LLMProvider.complete_json(JSONCompletionRequest) -> JSONCompletionResult` (text plus token usage). Selection by `LLM_PROVIDER=deepseek|gemini`, default DeepSeek (`deepseek-v4-pro` judge, `deepseek-flash` caller, base URL `https://api.deepseek.com`); Gemini model IDs stay env-pinned. Two verified DeepSeek facts shape the contract: JSON mode is `json_object` only, so the schema goes in the prompt and the caller validates; thinking mode is on by default and ignores temperature, so `thinking` defaults to `False`. `api_usage.provider` now allows `deepseek`. Providers are EVAL-01.

## 5. Tooling

`backend/pyproject.toml`: ruff (E, F, I, B, UP, RUF; line 100), mypy strict with the pydantic plugin (EVAL-02 modules checked but not yet fully annotated), pytest with asyncio and coverage config. Dev dependencies in `backend/requirements-dev.txt`.

## 4. Speech provider abstraction (VOICE-07, owner-approved 2026-10-24)

`backend/pareeksha/speech/base.py` defines `STTProvider` (`transcribe` batch, `transcribe_stream` live, `capabilities`: streaming, word timings, word confidence, diarization) and `TTSProvider` (`synthesize` to a WAV at a stated sample rate, `list_voices`, `capabilities`), plus the value types and errors. Providers: `gnani` (default, wraps `pareeksha.gnani`), `google`, `azure`, `elevenlabs`, `deepgram`. `speech/registry.py` selects by `STT_PROVIDER` / `TTS_PROVIDER` (default `gnani`) or per agent/run via `SpeechSelection{stt,tts}`. `GET /api/v1/speech/providers` (scope `read`) reports configured/default/capabilities. `pareeksha.gnani` is unchanged.
