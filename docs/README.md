# Pareeksha documentation

India-native crash testing and call auditing for voice AI agents. Synthetic Indian callers test bots before launch; the same judge audits real calls after launch. Dialect reports show where speech recognition fails, prompt and RAG tests catch problems before there is a voice bot, and results flow to HubSpot, webhooks and CI.

Start with the [project README](../README.md) for setup, configuration and known limitations.

## How it works

- **Speech:** Gnani Prisma (STT) and Timbre (TTS) by default. Google, Azure, ElevenLabs and Deepgram are implemented; only Gnani has been used in full evaluated runs.
- **LLM:** DeepSeek by default; Gemini is the alternative (`LLM_PROVIDER`). Admins can override the provider, models and key per project in **AI settings**. Ollama (optional `ollama` Compose profile) serves self-hosted embeddings and prompt-agent models.
- **Platform:** FastAPI API, Next.js web app, Postgres as the system of record, Kafka for work, Python SDK/CLI, GitHub Action, `pareeksha-audio-v1` and Pipecat agent adapters, Generic Webhook and HubSpot connectors.
- Postgres owns state; Kafka moves work through a transactional outbox, idempotent consumers, retry topics and a DLQ. A reconciler releases slots held by calls that failed for good.
- Hybrid evaluation: deterministic checks plus an LLM judge that cites evidence turns, scored in code against a versioned rubric (active: `rubric-2026-11-v3`). The same rubric scores simulated and real calls.

## Product flows

- **Pre-launch:** persona × scenario × noise profile → simulated call → recording, metrics and judge evaluation.
- **Post-launch audit:** uploaded or webhook-sourced recording → batch STT and diarization → role detection → evaluation.
- **Dialect report:** labelled clips → WER/CER/entity accuracy per group and audio condition → heatmap.
- **Prompt testing:** a prompt agent (versioned) talks to an LLM caller in text; the judge scores each conversation and versions can be compared.
- **RAG lab:** documents → indexes (chunking + embeddings) → generated or imported ground-truth questions → a matrix of retrieval setups compared on hit rate, hallucination, latency and cost.

Main Kafka flow: `run.requested → planner → call.requested → simulator → call.completed → evaluator → evaluation.completed → finalizer / integrations`. Other consumers: `auditor`, `dialect`, `generator` (scenario drafts), `indexer` (RAG indexes), `retrier` and `dlq-recorder`. Topics and operations: [guide 8](guides/08-operating-kafka.md).

## Documents

**Specification** (written before the build as v0.2 and kept in step with the code):

| Doc | Contents |
|---|---|
| [01-PRD](01-PRD.md) | Product requirements, scope and demo storyline |
| [02-requirements](02-requirements.md) | Functional and non-functional requirements |
| [03-TRD](03-TRD.md) | Technical requirements, stack, Kafka contracts |
| [04-system-design](04-system-design.md) | Components, data flow, failure handling |
| [05-database-design](05-database-design.md) | Postgres schema |
| [06-api-spec](06-api-spec.md) | REST API and the `pareeksha-audio-v1` protocol (`/openapi.json` is the source of truth) |
| [07-file-structure](07-file-structure.md) | Repository layout and ownership |
| [08-evaluation-rubric](08-evaluation-rubric.md) | Rubric, checks, judge and scoring |
| [10-integrations-and-dx](10-integrations-and-dx.md) | Connectors, adapters, SDK/CLI, `pareeksha.yaml`, GitHub Action |
| [contracts](contracts.md) | Frozen cross-team contracts |
| [SCOPE](SCOPE.md), [TEST_PLAN](TEST_PLAN.md) | Scope decisions and requirement-to-test mapping |

**Adopter guides:** [quick start](guides/01-quickstart.md), [Pipecat](guides/02-connect-pipecat.md), [any bot](guides/03-connect-any-bot.md), [webhook source](guides/04-webhook-source.md), [HubSpot](guides/05-hubspot.md), [GitHub Action](guides/06-github-action.md), [write a connector](guides/07-write-a-connector.md), [operating Kafka](guides/08-operating-kafka.md), [prompt testing](guides/09-prompt-testing.md), [RAG testing](guides/10-rag-testing.md), [SDK and CLI reference](guides/sdk-reference.md).

**Design:** [direction](design/direction.md), [references](design/references.md) and per-page specs in [design/pages](design/pages/).

**Demo:** [demo script](demo-script.md) and [3-minute version](demo-script-3min.md).

**Build history** (records of how the project was built; not updated as the code changes): [AGENTS.md](AGENTS.md) and [09-build-plan](09-build-plan.md) (multi-agent build plan), [orchestration](orchestration/) (goal and verifier rules), [superpowers](superpowers/) (design specs and plans for prompt and RAG testing).

## Verification

`make verify` runs acceptance checks V1–V11 and writes [`proof/FINAL_REPORT.md`](../proof/FINAL_REPORT.md); open items are tracked in [`STATUS.md`](../STATUS.md).
