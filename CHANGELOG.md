# Changelog

Contract changes after Day 1 need Tech Lead approval and an entry here.

## Inbound webhook source (INT-03) — 27 Oct 2026
- `POST /webhooks/inbound/{integration_id}` is real (the `STUB(INT-03)` handler). Shapes and status codes as documented (202/400/401/404/408/422); extra error codes `timestamp_out_of_window` (408), `unsafe_url` and `unknown_agent` (422). Additive: the built-in `webhook` connector now reports `direction: "both"` (it implements `ingest`; it was `"sink"` while only the sink existed) and its config gained optional `default_agent_id` (agent used when the payload's `agent_name` matches none). The frozen `Connector` interface is unchanged.
- `PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1` now also lets the import path (inbound URL check and recording download) reach a loopback host; unchanged otherwise.

## Evaluator and finalizer workers (EVAL-03b) — 24 Oct 2026
- Additive behaviour, no contract change: `run.completed` is emitted once per run with id `uuid5(run_id, "run.completed")` by the finalizer consumer or its every-minute completion reconciler (whichever wins the atomic claim), also for runs the API cancelled (status stays `cancelled`; only `summary` and `finished_at` are filled). `Outgoing` (consumer framework) gained an optional `event_id`. `run_items` move `completed -> evaluating` while the judge runs. See `docs/contracts.md` section 1.
## Audit pipeline (EVAL-04) — 24 Oct 2026
- **Contract change (additive, needs TL/owner approval, raised as an ISSUE by EVAL-04):** `STTProvider.transcribe(..., denoise: bool = False)` and `STTCapabilities.denoise` (default `False`). Gnani passes it to the batch job (`denoise=True`); google, azure, elevenlabs and deepgram raise `UnsupportedCapabilityError` when it is requested (the TRD requires "diarize, denoise" for audits). Existing callers are unaffected.
- `POST /audits` and `POST /calls/{id}/speaker-map` are real (the two `STUB(EVAL-04)` handlers). No change to their documented request/response shapes; speaker-map answers `400` for unknown or incomplete roles and `409` when the call is not an uploaded/imported, completed call.
- New runtime pieces (no frozen contract touched): `pareeksha/audit/` (ingest, turns, role detection, pipeline), `pareeksha/storage/blob.py` (`BlobStore`, `DATA_DIR`), prompt `role_detect_v1.j2`, workers `auditor` and `evaluator` (the latter with the Postgres store `evaluation/store.py`, so audits and simulations share one code path), `events/outbox.enqueue_session`. `soundfile` is now a declared backend dependency (WAV/MP3 decode).

## Speech provider abstraction (VOICE-07) — 24 Oct 2026
- **Contract change: speech provider abstraction (owner-approved 2026-10-24).** New `backend/pareeksha/speech/` with `STTProvider` / `TTSProvider` interfaces, capability metadata, registry selected by `STT_PROVIDER` / `TTS_PROVIDER` (default `gnani`, overridable per agent/run with `SpeechSelection`), adapters for gnani (wrapping the unchanged `pareeksha.gnani`), google, azure, elevenlabs, deepgram. New route `GET /api/v1/speech/providers` (76 operations now; `/health` keeps its `{db,kafka}` shape). New env: `STT_PROVIDER`, `TTS_PROVIDER`, `GOOGLE_APPLICATION_CREDENTIALS_JSON`, `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `ELEVENLABS_API_KEY`, `DEEPGRAM_API_KEY` and per-vendor model/voice/`COST_*` variables (see `.env.example`).
- **Contract change (same):** `api_usage.provider` CHECK and `UsageRow.provider` now also allow `google`, `azure`, `elevenlabs`, `deepgram` (docs/schema.sql, Alembic 0001 and its SQL copy, `web/lib/api/schema.d.ts`).

## Contracts frozen as code (TL-01) — 23 Oct 2026
- **Contract change: LLM provider abstraction, DeepSeek default (owner-approved 2026-10-23).** `backend/pareeksha/llm/base.py` defines `LLMProvider.complete_json(JSONCompletionRequest) -> JSONCompletionResult` (text plus token usage, text-only JSON mode); `llm/config.py` reads `LLM_PROVIDER=deepseek|gemini` (default `deepseek`) and the `DEEPSEEK_*`, `GEMINI_*` and `COST_*` variables in `.env.example`. Supersedes the Gemini-only wording of `03-TRD.md` section 4 (`GeminiClient.generate_json`) and `06-api-spec.md` ("pinned gemini id"); providers are implemented by EVAL-01. `docs/schema.sql`: `api_usage.provider` now also allows `'deepseek'`.
- Contracts committed: `events/topics.py` (12 topics, keys, partitions, retention, retry/DLQ headers), `events/schemas.py` (envelope plus 9 payloads), `integrations/base.py` (Connector ABC), `adapters/base.py` (AudioSession, Adapter, `pareeksha-audio-v1` messages), FastAPI app with every route of `06-api-spec.md` declared (501 stubs, each marked `# STUB(<owner task>)`).
- **API additions** (docs/design/pages/00-shared.md section 11 gaps G-1, G-2, G-3, G-7, G-9 to G-13, each backed by an FR; see `06-api-spec.md` section 12): `POST /runs:estimate`, `GET /calls`, `GET /regression-tests`, `PATCH /regression-tests/{id}`, `GET /dialect-datasets`, `GET /dialect-reports`, `GET /dialect-reports/{id}/clips`, `GET /dialect-reports/{id}/html` (referenced by the original spec), list filters on `GET /runs`, `RunSummary.score_distribution`, `run_id` on calls.
- API conventions fixed: routes live under `/api/v1`; validation failures are `400 validation_error` (FastAPI's default 422 is removed from OpenAPI); `/health` is also served unprefixed for Docker Compose.

## Docs v0.2 — 23 Oct 2026
- **Kafka event backbone** replaces the Postgres job queue: 12 versioned topics, JSON envelope, transactional outbox, idempotent consumers (`processed_events`), retry topics (30 s, 5 min) and DLQ, per-run concurrency slots (`test_runs.active_calls`).
- `pareeksha.call.requested.v1` keyed by **run_item_id** (the draft playbook keyed it by run_id, which would have serialised each run onto one partition).
- **Next.js web app** replaces Streamlit: BFF proxy keeps API keys server-side, generated OpenAPI client, SSE live progress, waveform call detail.
- **Adoption:** API keys with scopes, Python SDK + CLI, `pareeksha.yaml`, GitHub Action, agent adapters (`audio_v1`, Pipecat; LiveKit/Vapi optional), `docker compose up` + `make demo`.
- **Integrations:** connector framework with entry-point plugins; Generic Webhook (source + sink, HMAC) and HubSpot sink in v1.
- Schema: removed `jobs`; added `outbox_events`, `processed_events`, `dead_letters`, `integrations`, `integration_deliveries`, `external_refs`, `api_keys`, `scenario_drafts`; `agents.adapter`; `calls.source = import`, `calls.metadata`.
- New docs: `10-integrations-and-dx.md`, `AGENTS.md`, `STATUS.md`, `starter/docker-compose.yml`, `starter/infra/kafka/create-topics.sh`.
- Build plan shortened from 18 days to 5 days (multi-agent).

## Docs v0.1 — 23 Oct 2026
- Initial PRD, requirements, TRD, system design, schema, API spec, file structure, rubric, 18-day plan.
- Verified against packages: Gnani SDK endpoints/voices, `pipecat-gnani` (no `pipecat-ai[gnani]` extra), Timbre v2.5 has only 2 Kannada voices; Indian PSTN uses G.711 A-law.

## 2026-10-23
- Owner approval (Preetham): DES-01 design direction "Field Instrument" approved.
- Owner decision (Preetham): DeepSeek is the default LLM provider; Gemini remains supported (contract change via TL-01).
- 2026-10-24 Owner approval (Preetham): TL-01 contracts approved and frozen (docs/contracts.md: scopes, 400 validation errors, stub owners, DeepSeek defaults deepseek-v4-pro / deepseek-flash).

## 2026-10-27 — VOICE-06 (additive, no frozen contract changed)
- `agents.adapter = "pipecat"` is now served by `PipecatAdapter` (`pareeksha.adapters.registry`); the wire protocol is unchanged `pareeksha-audio-v1`. New module `pareeksha.adapters.pipecat_serializer` (`PareekshaFrameSerializer`, `GlassBoxProcessor`) is the bot-side half. LiveKit (Should) and Vapi (Could) are not built; they remain `AdapterUnavailableError` and their cut needs the owner's written approval (AGENTS §10).
## 2026-10-27 — EVAL-04b (additive, no frozen contract changed)
- Audits with low-confidence or heuristic-vs-LLM-disagreeing role detection set `needs_human_review` (new `review_reasons` values, docs/contracts.md §4.2).
- Per-agent STT/TTS provider override stored in `agents.adapter_config["speech"]` (docs/contracts.md §4.1); validated on create/patch, honoured by the auditor.
