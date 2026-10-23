# 07 — File Structure · v0.2

Monorepo with four deliverables: the **backend** (Python package + workers), the **web** app (Next.js), the **SDK/CLI** and the **GitHub Action**. They share one contract: the OpenAPI spec and the Kafka event schemas.

```
pareeksha/                                   ← repo root
├── README.md                                # pitch, demo GIF, quick start, architecture, limitations
├── AGENTS.md                                # multi-agent build playbook (roles, contracts, 5-day task board)
├── STATUS.md                                # live task board (orchestrator/PJM keep it current)
├── CHANGELOG.md                             # contract changes + releases
├── docker-compose.yml                       # kafka, kafka-init, postgres, api, outbox-relay, workers, web, mock-agent
├── Makefile                                 # up, down, seed, demo, test, e2e, lint, gen-api
├── .env.example
├── .github/workflows/ci.yml                 # lint, unit, contract, kafka integration, playwright smoke
│
├── docs/                                    # this documentation pack
│
├── infra/
│   ├── kafka/create-topics.sh               # idempotent topic creation (used by kafka-init)
│   ├── kafka/topics.yaml                    # topic list = single source of truth (mirrors events/topics.py)
│   └── postgres/init.sql                    # creates db/user (schema comes from Alembic)
│
├── backend/
│   ├── pyproject.toml                       # package "pareeksha", entry points incl. pareeksha.connectors
│   ├── Dockerfile                           # one image for api + every worker
│   ├── alembic.ini
│   ├── pareeksha/
│   │   ├── config.py  logging.py  clock.py  crypto.py   # crypto = Fernet helpers
│   │   │
│   │   ├── db/
│   │   │   ├── engine.py  models.py  enums.py
│   │   │   ├── repo/                         # agents, runs, calls, evaluations, dialect, integrations, usage
│   │   │   └── migrations/versions/0001_initial.py   # = docs/schema.sql
│   │   │
│   │   ├── events/                          # ★ Kafka layer — owned by BE-INFRA
│   │   │   ├── topics.py                     # Topics enum, partitions, retention
│   │   │   ├── schemas.py                    # Envelope[T] + one Pydantic payload per event type
│   │   │   ├── producer.py                   # aiokafka producer (acks=all, idempotence)
│   │   │   ├── consumer.py                   # @consumer decorator: idempotency, tx, retry/DLQ, shutdown
│   │   │   ├── outbox.py                     # add_outbox_event(session, topic, key, payload)
│   │   │   ├── retry.py                      # classify errors, route to retry.30s / retry.5m / dlq
│   │   │   └── ids.py                        # deterministic output event ids (uuid5)
│   │   │
│   │   ├── workers/                         # one module per consumer group (thin: wire handler → framework)
│   │   │   ├── outbox_relay.py  planner.py  simulator.py  auditor.py  evaluator.py
│   │   │   ├── finalizer.py  integrations.py  dialect.py  generator.py
│   │   │   └── retrier.py  dlq_recorder.py
│   │   │
│   │   ├── api/
│   │   │   ├── main.py  deps.py  auth.py      # auth = API keys + scopes
│   │   │   ├── sse.py                         # progress topic → per-run SSE streams
│   │   │   └── routers/
│   │   │       ├── agents.py  scenarios.py  personas.py  noise_profiles.py
│   │   │       ├── runs.py  calls.py  audits.py  dialect.py  regression.py
│   │   │       ├── integrations.py  webhooks.py  dlq.py  api_keys.py  system.py
│   │   │
│   │   ├── schemas/                          # API + LLM Pydantic models
│   │   ├── gnani/                            # wrappers over gnani-vachana (+ cache, usage logging)
│   │   ├── llm/                              # GeminiClient + prompts/*.j2
│   │   ├── audio/                            # DSP + LineSimulator (no network)
│   │   ├── adapters/                        # ★ agent adapters
│   │   │   ├── base.py                       # AudioSession interface
│   │   │   ├── audio_v1.py  pipecat.py  livekit.py  vapi.py
│   │   │   └── pipecat_serializer.py         # PareekshaFrameSerializer (also exported via SDK)
│   │   ├── simulation/                       # Pipecat caller pipeline + processors (uses adapters/)
│   │   ├── evaluation/                       # metrics, checks, numbers, pii, judge, scoring, calibration
│   │   ├── audit/                            # ingest, batch STT pipeline, role detection
│   │   ├── dialect/                          # textnorm, asr_eval, aggregate, report
│   │   ├── regression/                       # promote, suite
│   │   ├── runs/                             # matrix, estimate, finalize, slots (active_calls)
│   │   ├── integrations/                    # ★ connector framework
│   │   │   ├── base.py                       # Connector protocol, TestResult, AuditRequest, EvaluationSummary
│   │   │   ├── registry.py                   # entry-point discovery
│   │   │   ├── signing.py                    # HMAC sign/verify, timestamp window
│   │   │   ├── ssrf.py                       # safe URL fetch for recordings
│   │   │   ├── webhook/connector.py          # generic webhook source + sink
│   │   │   └── hubspot/connector.py          # HubSpot sink
│   │   ├── storage/blob.py
│   │   └── reports/templates/                # run + dialect HTML
│   └── tests/
│       ├── unit/  contract/  kafka/  connectors/  judge/  e2e/
│       └── fixtures/
│
├── web/                                     # ★ Next.js 16 app — owned by FE
│   ├── package.json  next.config.ts  tsconfig.json  components.json (shadcn)
│   ├── middleware.ts                         # optional WEB_PASSWORD gate
│   ├── app/
│   │   ├── layout.tsx  page.tsx               # overview
│   │   ├── api/proxy/[...path]/route.ts       # BFF proxy to FastAPI (adds API key, streams SSE)
│   │   ├── agents/  agents/[id]/
│   │   ├── scenarios/  personas/  noise-profiles/
│   │   ├── runs/  runs/new/  runs/[id]/  runs/compare/
│   │   ├── calls/[id]/
│   │   ├── audits/
│   │   ├── dialect/  dialect/[id]/
│   │   ├── regression/
│   │   ├── integrations/  integrations/[id]/
│   │   ├── dlq/
│   │   ├── calibration/
│   │   └── settings/api-keys/
│   ├── components/
│   │   ├── ui/                                # shadcn primitives
│   │   ├── call/ (Waveform, Transcript, EvidenceTurn, DimensionScores, ChecksList, PromoteDialog)
│   │   ├── run/ (MatrixHeatmap, ProgressBar, LatencyChart, RunWizard)
│   │   ├── dialect/ (DialectHeatmap, WorstClips)
│   │   └── integrations/ (ConnectorForm, DeliveryLog)
│   ├── lib/
│   │   ├── api/schema.d.ts                    # generated by openapi-typescript (do not edit)
│   │   ├── api/client.ts  api/hooks.ts        # openapi-fetch + TanStack Query hooks
│   │   ├── sse.ts                              # EventSource wrapper with polling fallback
│   │   └── score.ts                            # score → colour scale (from DES tokens)
│   └── tests/ (Playwright)
│
├── sdk/python/                              # ★ pareeksha-sdk + CLI — owned by INT
│   ├── pyproject.toml                        # console_scripts: pareeksha = pareeksha_sdk.cli:app
│   ├── pareeksha_sdk/
│   │   ├── client.py  models.py (generated)  runs.py  audits.py  agents.py
│   │   ├── config_file.py                     # pareeksha.yaml loader + apply
│   │   ├── agent_server.py                    # helper to expose any bot via pareeksha-audio-v1
│   │   └── cli.py
│   └── tests/
│
├── action/                                  # ★ GitHub Action — owned by INT
│   ├── action.yml
│   └── summary.py                            # writes $GITHUB_STEP_SUMMARY
│
├── mock_agent/                              # demo bot with 5 planted bugs — owned by VOICE
│   ├── server.py  bot.py  prompt.j2  tools.py  bugs.py  Dockerfile
│
├── examples/
│   ├── pipecat-bot/                          # minimal Pipecat bot + PareekshaFrameSerializer
│   ├── custom-bot-audio-v1/                  # any bot via agent_server helper
│   ├── livekit-bot/                          # (Should)
│   ├── pareeksha.yaml                        # config-as-code example
│   └── github-workflow.yml
│
└── data/
    ├── seeds/ personas.yaml  noise_profiles.yaml  scenarios_emi.yaml  rubric-2026-10-v1.yaml
    ├── noise/<category>/*.wav  + LICENSES.md
    ├── dialect/                              # consented clips + manifest.csv (git-ignored)
    └── runtime/                              # DATA_DIR (git-ignored)
```

## Ownership (matches AGENTS.md roles)

| Path | Owner |
|---|---|
| `backend/pareeksha/events/`, `workers/` framework, `infra/`, `docker-compose.yml`, CI | BE-INFRA |
| `backend/pareeksha/api/`, `db/`, `runs/`, `regression/`, `schemas/` | BE-API |
| `backend/pareeksha/gnani/`, `audio/`, `adapters/`, `simulation/`, `mock_agent/`, `examples/*-bot` | VOICE |
| `backend/pareeksha/llm/`, `evaluation/`, `audit/`, `dialect/` | EVAL |
| `backend/pareeksha/integrations/`, `sdk/`, `action/` | INT |
| `web/` | FE (specs from DES) |
| `backend/tests/e2e`, `web/tests`, test plan | QA |
| `docs/`, `README.md`, `examples/` docs | DOC |
| `events/schemas.py`, `integrations/base.py`, `adapters/base.py`, OpenAPI | TL (frozen contracts) |

## Dependency rules

```
web ──HTTP──► api          sdk/action ──HTTP──► api          (no Python imports from web or sdk into backend)
api ──► db, events.outbox, schemas, integrations.signing
workers ──► simulation, audit, evaluation, dialect, integrations, runs ──► audio, gnani, llm, adapters, storage, db, events
audio ──► nothing (pure functions)
```
- Only `gnani/`, `llm/`, `adapters/` and `integrations/*/connector.py` touch the network (plus `events/` for Kafka).
- The API never calls Gnani, Gemini or CRMs directly — it writes outbox events. Exception: persona/noise previews.
- `web/lib/api/schema.d.ts` and `sdk/python/pareeksha_sdk/models.py` are generated; CI fails if stale.
