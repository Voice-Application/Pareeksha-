# Changelog

Contract changes after Day 1 need Tech Lead approval and an entry here.

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
