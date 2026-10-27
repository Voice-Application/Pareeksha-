# Pareeksha — Documentation Pack v0.2

> **Pareeksha** (ಪರೀಕ್ಷೆ / परीक्षा, "test") is a working name. Rename freely.

**One line:** An India-native crash-testing and call-audit platform for voice AI agents. Synthetic Indian callers (Kannada, Hindi, Hinglish/Kanglish, noisy phone lines) attack a voice bot before launch; the same judge audits real calls after launch; a dialect report shows where speech recognition breaks; and results flow into the team's CRM and CI.

**Stack:** pluggable speech (Gnani Prisma/Timbre default; Google, Azure, ElevenLabs, Deepgram selectable) · DeepSeek (caller brain + judge; Gemini optional) · Pipecat · **Kafka** event backbone · Postgres · FastAPI · **Next.js** web app · Python SDK/CLI · HubSpot + webhook connectors.

**What's new in v0.2:** Kafka replaces the Postgres job queue · Next.js replaces Streamlit · built for other teams to adopt (SDK, CLI, GitHub Action, adapters, one-command setup) · CRM/webhook connector framework · 5-day multi-agent build plan. Details in [CHANGELOG.md](../CHANGELOG.md).

---

**Decisions made during the build (they supersede older text in this pack):**
- **LLM:** DeepSeek is the default for the caller brain, judge, scenario generation, role detection and ASR intent (`LLM_PROVIDER=deepseek`); Gemini is the supported alternative (`LLM_PROVIDER=gemini`). Where these docs say "Gemini judge", read "the configured LLM judge".
- **Speech is pluggable:** `STT_PROVIDER` / `TTS_PROVIDER` = `gnani` (default, verified live) | `google` | `azure` | `elevenlabs` | `deepgram`. The last four are implemented and unit-tested; their keys are pending, so they are not yet verified live. Overridable per agent/run.
- **SDK:** distribution `pareeksha-sdk`, import name **`pareeksha_sdk`** (not `pareeksha`, which is the backend package); CLI command `pareeksha`. The `agent_server` helper in the file tree was not built; Guide 3 shows a ~20-line server instead.
- **Dev switch:** `PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1` lets webhooks/recording fetches target loopback/private addresses for local testing only (https, no-credentials and IP pinning still apply). Never set it in production.
- **No `make demo`:** setup is `docker compose --profile workers up -d --build` then `docker compose run --rm api python -m pareeksha.seed`; see [Guide 1](guides/01-quickstart.md).

**Adopter guides:** [1 Quick start](guides/01-quickstart.md) · [2 Pipecat bot](guides/02-connect-pipecat.md) · [3 Any bot (`pareeksha-audio-v1`)](guides/03-connect-any-bot.md) · [4 Webhook source](guides/04-webhook-source.md) · [5 HubSpot](guides/05-hubspot.md) · [6 GitHub Action](guides/06-github-action.md) · [7 Write a connector](guides/07-write-a-connector.md) · [8 Operating Kafka](guides/08-operating-kafka.md) · [SDK reference](guides/sdk-reference.md)

## How to read this folder

| # | File | What it answers |
|---|------|-----------------|
| 1 | [01-PRD.md](01-PRD.md) | What, for whom, why; features; success metrics; demo storyline |
| 2 | [02-requirements.md](02-requirements.md) | Numbered functional + non-functional requirements with acceptance tests |
| 3 | [03-TRD.md](03-TRD.md) | How each part is built — incl. Kafka topics, outbox, retries/DLQ (§10) and the web app (§11) |
| 4 | [04-system-design.md](04-system-design.md) | Architecture, event flow, sequence diagrams, scaling, trade-offs |
| 5 | [05-database-design.md](05-database-design.md) | ER diagram, every table, key queries |
| 6 | [schema.sql](schema.sql) | Runnable PostgreSQL DDL (29 tables, tested on Postgres 16) |
| 7 | [06-api-spec.md](06-api-spec.md) | REST endpoints, SSE, webhooks, DLQ, API keys, agent audio protocol |
| 8 | [07-file-structure.md](07-file-structure.md) | Monorepo layout + who owns what |
| 9 | [08-evaluation-rubric.md](08-evaluation-rubric.md) | Judge rubric, metrics, noise profiles, personas, dialect WER method |
| 10 | [09-build-plan.md](09-build-plan.md) | 5-day plan summary + your own tasks |
| 11 | [10-integrations-and-dx.md](10-integrations-and-dx.md) | Connector framework, HubSpot/webhook, SDK, CLI, GitHub Action, adapters |
| — | [AGENTS.md](AGENTS.md) | **The multi-agent playbook**: roles, rules, frozen contracts, task board, cut list |
| — | [STATUS.md](../STATUS.md) | Live task board template |
| — | [CHANGELOG.md](../CHANGELOG.md) | What changed between doc versions |
| — | [starter/docker-compose.yml](starter/docker-compose.yml) | Full local stack (Kafka KRaft, Postgres, API, workers, web, mock agent) |
| — | [starter/infra/kafka/create-topics.sh](starter/infra/kafka/create-topics.sh) | Idempotent topic creation |
| — | [requirements.txt](../requirements.txt) · [.env.example](../.env.example) | Backend deps (+ web/SDK deps listed) · environment variables |

**For the orchestrator:** load `AGENTS.md` first; it references everything else by section.

---

## The product in 30 seconds

```
 PRE-LAUNCH (crash test)        POST-LAUNCH (audit)              ASR (dialect report)
 Persona × scenario × noise     Recording via upload or          Native-speaker clips
        ↓                       signed webhook (telephony/CRM)   + reference text
 Simulated caller calls bot            ↓                                ↓
 (Timbre TTS + phone noise)     Prisma batch STT + diarization   Prisma under clean / 8 kHz / noise
        ↓                              ↓                                ↓
 Record → metrics → Gemini judge (same rubric everywhere)       WER / CER / entity accuracy
        └──────────────┬──────────────┘                                 ↓
                       ↓                                        Dialect × condition heatmap
     Next.js app (live) · HubSpot note · webhook · GitHub Action check
```

Under the hood every step is a Kafka consumer group: `run.requested → planner → call.requested → simulator → call.completed → evaluator → evaluation.completed → finalizer / integrations`.

## Key decisions

1. **Postgres owns state, Kafka moves work.** Transactional outbox in, idempotent consumers out, retry topics + DLQ for failures. At-least-once delivery, effectively-once side effects.
2. **Hybrid evaluation.** Code checks hard facts; the LLM judges meaning; critical failures always go to a human.
3. **Same rubric everywhere** — simulated and real calls are comparable.
4. **Real voices for dialect claims**; synthetic voices only for crash testing.
5. **Adapters, not lock-in.** Any bot via `pareeksha-audio-v1`; Pipecat first-class; LiveKit/Vapi next.
6. **Connectors are plugins.** HubSpot + webhook in v1; anyone can add Zoho/Salesforce as a pip package.
7. **Synthetic data only**; transcripts never leave for CRMs unless explicitly enabled.

## Verified vs still to verify

**Verified on 23 Oct 2026:**
- Gnani SDK (`gnani-vachana` 0.8.2): base URL, `X-API-Key-ID` header, STT/TTS paths, 10 language codes, Timbre models, voice lists (v2.5 has only 2 Kannada voices; v3.0 has 13 multilingual voices).
- Pipecat + Gnani comes from the separate `pipecat-gnani` package; Pipecat has no `[gnani]` extra.
- Package versions on PyPI/npm: aiokafka 0.14, Pipecat 1.13, Next.js 16, React 19, TanStack Query 5, openapi-typescript 7, wavesurfer.js 8.
- `schema.sql` applies on Postgres 16; the outbox claim, idempotency insert and per-run slot queries behave as designed.
- `starter/docker-compose.yml` passes `docker compose config`; the topic script passes a bash syntax check.
- The SNR mixing formula hits target SNRs exactly.

**Still to verify on Day 1–3 (by calling the services):**
- Timbre v3.0 access on your key; how code-mixed text sounds with `kn-IN`/`hi-IN` vs `auto`.
- Telephony tuning headers and batch diarization/denoise option names; credit cost per minute.
- The `apache/kafka:4.0.0` image tag actually starting (no Docker daemon was available to test).
- HubSpot search/notes endpoints, association type and private-app scopes (build against a mock first).
- Vapi's WebSocket transport details (only matters if the Vapi adapter is attempted).
- The exact Gemini model ID to pin.

## Open decisions
- [ ] Final product name
- [ ] Demo bot scenario (default: EMI payment reminder bot)
- [ ] Optional comparator ASR for the dialect report (Whisper vs none)
- [ ] Hosted demo after v1 (managed Kafka + Vercel for the web app) or local-only
