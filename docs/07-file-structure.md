# 07 — File Structure · v0.2

Monorepo with four deliverables: the **backend** (Python package + workers), the **web** app (Next.js), the **SDK/CLI** and the **GitHub Action**. They share one contract: the OpenAPI spec and the Kafka event schemas.

```
pareeksha/                                   ← repo root
├── README.md                                # pitch, quick start, architecture, limitations
├── STATUS.md  NOTES.md                      # live task board; vendor/probe findings
├── CHANGELOG.md                             # contract changes + releases
├── docker-compose.yml                       # kafka, kafka-init, postgres, migrate, api, outbox-relay, planner, simulator,
│                                            #   auditor, evaluator, finalizer, integrations, dialect, generator, indexer,
│                                            #   retrier, dlq-recorder, web, mock-agent, kafka-ui, ollama
├── docker-compose.proxy.yml                 # compose override for proxy setups
├── Makefile                                 # demo, verify, verify-step, lint, test
├── requirements.txt                         # root dependency list (lower bounds)
├── .env.example
├── .github/workflows/                       # ci.yml, kafka-suite.yml, pareeksha-regression.yml, release.yml
│
├── docs/                                    # this documentation pack (+ guides/, design/, starter/, orchestration/)
│
├── infra/
│   └── kafka/create-topics.sh               # idempotent topic creation (used by kafka-init)
│                                            # (no postgres/ dir: db/user come from compose env, schema from Alembic)
│
├── backend/
│   ├── pyproject.toml                       # package "pareeksha"; entry-point group pareeksha.connectors (webhook, hubspot)
│   ├── requirements-dev.txt  requirements.lock
│   ├── Dockerfile                           # one image for api + every worker
│   ├── alembic.ini  alembic_migrate.sh
│   ├── alembic/versions/                    # 0001_initial … 0007_repair_project_columns
│   ├── pareeksha/
│   │   ├── db/
│   │   │   ├── models.py                     # all SQLAlchemy models
│   │   │   ├── session.py                    # engine / session
│   │   │   └── queries.py
│   │   │
│   │   ├── events/                          # ★ Kafka layer — owned by BE-INFRA
│   │   │   ├── topics.py                     # topic names, partitions, retention
│   │   │   ├── schemas.py                    # Envelope + one Pydantic payload per event type
│   │   │   ├── producer.py                   # aiokafka producer
│   │   │   ├── consumer.py                   # consumer framework: idempotency, tx, retry/DLQ, shutdown
│   │   │   ├── outbox.py                     # outbox writes
│   │   │   └── runtime.py  settings.py       # worker runtime + Kafka settings
│   │   │
│   │   ├── workers/                         # one module per consumer group (thin: wire handler → framework)
│   │   │   ├── outbox_relay.py  planner.py  simulator.py  auditor.py  evaluator.py  judge.py
│   │   │   ├── finalizer.py  integrations.py  dialect.py  generator.py  indexer.py
│   │   │   └── retrier.py  dlq_recorder.py  reconciler.py  _outgoing.py
│   │   │
│   │   ├── api/
│   │   │   ├── main.py  deps.py  auth.py  passwords.py   # API keys + user sessions
│   │   │   ├── crud.py  errors.py  health.py  ratelimit.py  body_limit.py  outbox.py
│   │   │   ├── connectors.py  speech.py  llm_deps.py
│   │   │   └── routers/
│   │   │       ├── agents.py  scenarios.py  personas.py  noise_profiles.py  prompt_versions.py
│   │   │       ├── runs.py  calls.py  audits.py  dialect.py  regression.py  quick_tests.py
│   │   │       ├── knowledge_bases.py  rag_matrices.py  designer.py
│   │   │       └── integrations.py  webhooks.py  dlq.py  api_keys.py  users.py  settings.py  system.py
│   │   │
│   │   ├── schemas/                          # API + LLM Pydantic models
│   │   ├── gnani/                            # clients over gnani-vachana
│   │   ├── speech/                           # provider-neutral STT/TTS: base, registry, config, providers/
│   │   │                                     #   (gnani, deepgram, elevenlabs, azure, google)
│   │   ├── llm/                              # LLM client + providers (deepseek, gemini), usage_db, project_settings, prompts/*.j2
│   │   ├── agent_llm/                        # LLM backends for prompt-based agents under test (openai_compat, anthropic, gemini)
│   │   ├── audio/                            # DSP, noise, profiles, LineSimulator, previews (no network)
│   │   ├── adapters/                        # ★ agent adapters
│   │   │   ├── base.py  registry.py          # AudioSession interface; adapter registry
│   │   │   ├── audio_v1.py  pipecat_adapter.py  connection_check.py
│   │   │   └── pipecat_serializer.py         # PareekshaFrameSerializer
│   │   ├── simulation/                       # caller pipeline, runner, text_runner, processors, VAD, barge-in, recorder
│   │   ├── evaluation/                       # metrics, checks, numbers, pii, judge, rubric, scoring, calibration, completion reconciler
│   │   ├── audit/                            # ingest, batch STT pipeline, role detection
│   │   ├── dialect/                          # normalize, intent, metrics, stats, pipeline, report (+ loanwords.yaml)
│   │   ├── regression/                       # promote, verdict, outcomes, estimate
│   │   ├── runs/                             # service, matrix, estimate, slots, stream (SSE), watchdog, compare, report
│   │   ├── calls/                            # call service + audio access
│   │   ├── quicktest/                        # prompt quick tests (service + assistant)
│   │   ├── rag/                              # knowledge bases: extract, chunking, embeddings, BM25, rerank, retriever, matrix, questions, report
│   │   ├── designer/                         # designer service
│   │   ├── scenario_gen/                     # LLM scenario generation
│   │   ├── ops/                              # dlq, metrics
│   │   ├── integrations/                    # ★ connector framework
│   │   │   ├── base.py  registry.py          # Connector protocol; entry-point discovery
│   │   │   ├── signing.py  crypto.py         # HMAC sign/verify; Fernet secrets
│   │   │   ├── ssrf.py  redact.py            # safe URL fetch; secret redaction
│   │   │   ├── dispatch.py  delivery.py  sql_store.py
│   │   │   ├── webhook.py                    # generic webhook source + sink
│   │   │   └── hubspot.py                    # HubSpot sink
│   │   ├── storage/blob.py
│   │   └── seed/                             # seed runner + data/ (personas, scenarios, rubrics v1–v3, demo agent/KB/prompt/RAG)
│   └── tests/
│       ├── unit/  contract/  db/  evaluation/  integration/  judge/  kafka/  e2e/
│       └── fixtures/
│
├── web/                                     # ★ Next.js 16 app — owned by FE
│   ├── package.json  next.config.ts  tsconfig.json  components.json (shadcn)
│   ├── proxy.ts                              # Next 16 "proxy" (ex-middleware): signed-session account gate
│   ├── app/
│   │   ├── layout.tsx  login/  welcome/       # sign-in; public landing page
│   │   ├── api/proxy/[...path]/route.ts       # BFF proxy to FastAPI (adds API key, streams SSE)
│   │   ├── api/auth/{login,logout,setup}/     # session endpoints
│   │   └── (dashboard)/
│   │       ├── page.tsx                       # overview
│   │       ├── agents/  scenarios/  personas/  noise-profiles/  designer/
│   │       ├── runs/ (new, [id], compare)  calls/[id]  test/ (quick tests)
│   │       ├── audits/  dialect/  regression/  calibration/
│   │       ├── knowledge-bases/  rag-lab/
│   │       ├── integrations/  dlq/
│   │       └── settings/{api-keys,llm,pricing,users}/
│   ├── components/                            # feature folders (agents, runs, calls, rag, quick, designer, …) + ui/ (shadcn)
│   ├── lib/
│   │   ├── api/schema.d.ts                    # generated by openapi-typescript (do not edit)
│   │   ├── api/client.ts  + per-area modules  # openapi-fetch clients
│   │   ├── hooks/                             # shared React hooks
│   │   └── session.ts  auth-server.ts  nav.ts  admin-routes.ts  …
│   └── tests/ (Playwright; real/ = against a live stack)
│
├── sdk/python/                              # ★ pareeksha-sdk + CLI — owned by INT
│   ├── pyproject.toml                        # console_scripts: pareeksha = pareeksha_sdk.cli:app
│   ├── pareeksha.example.yaml
│   ├── src/pareeksha_sdk/
│   │   ├── client.py  models.py (generated)  _calls.py  errors.py
│   │   ├── config.py  apply.py                # pareeksha.yaml loader + apply
│   │   ├── summary.py                         # run summary (Markdown)
│   │   └── cli.py
│   └── tests/
│
├── action/
│   └── action.yml                            # GitHub Action (applies config, runs suite, writes job summary via the SDK)
│
├── mock_agent/                              # demo bot with planted bugs — owned by VOICE
│   └── server.py  policy.py  bugs.py  llm_dialog.py  speech.py  vad.py  Dockerfile  README.md
│
├── examples/
│   ├── pipecat-bot/                          # minimal Pipecat bot + PareekshaFrameSerializer
│   ├── connector-slack/                      # third-party connector example (entry point)
│   └── ci/pareeksha.yaml                     # config-as-code example for CI
│
├── scripts/                                 # smoke/demo/verification helpers (calibration/, ci/, data/, demo/, verify/)
├── labelling/  proof/                       # human-label packets; per-task evidence
└── data/
    └── dialect/                              # dialect clips (vaani)
```

## Ownership (matches AGENTS.md roles)

| Path | Owner |
|---|---|
| `backend/pareeksha/events/`, `workers/` framework, `infra/`, `docker-compose.yml`, CI | BE-INFRA |
| `backend/pareeksha/api/`, `db/`, `runs/`, `regression/`, `schemas/` | BE-API |
| `backend/pareeksha/gnani/`, `speech/`, `audio/`, `adapters/`, `simulation/`, `mock_agent/`, `examples/pipecat-bot` | VOICE |
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
workers ──► simulation, audit, evaluation, dialect, rag, quicktest, integrations, runs ──► audio, gnani/speech, llm, adapters, storage, db, events
audio ──► nothing (pure functions)
```
- Network access is confined to `gnani/`, `speech/`, `llm/`, `agent_llm/`, `adapters/`, `rag/` (embeddings/rerank), `integrations/` connectors (plus `events/` for Kafka).
- The API does not call speech providers, the LLM or CRMs for run/audit work — it writes outbox events. Exceptions: persona/noise previews, agent connection tests, and interactive designer/quick-test/speech endpoints.
- `web/lib/api/schema.d.ts` and `sdk/python/src/pareeksha_sdk/models.py` are generated; CI fails if stale (`backend/tests/contract/test_schema_dts_fresh.py`).
