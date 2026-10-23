# Changelog

Contract changes after Day 1 need Tech Lead approval and an entry here.

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
