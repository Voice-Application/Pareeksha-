# AGENTS.md — Pareeksha Multi-Agent Build Plan (5 days)

Operating manual for the AI agent team building Pareeksha. The **Orchestrator** reads this first, assigns tasks by ID, and enforces the rules. Every agent reads §1–§6 before starting any task.

- **Timeline:** Sat 24 Oct → Wed 28 Oct 2026 (5 days).
- **Human owner and final approver:** Preetham.
- **Spec:** `docs/` v0.2 (this pack). v0.2 already includes the four changes below — agents build from the docs directly.

## 1. The four v0.2 changes (already applied in docs)

1. **Kafka is the event backbone** (KRaft, no ZooKeeper; `aiokafka`). Postgres stays the system of record. Transactional outbox, idempotent consumers, retry topics + DLQ. → `03-TRD.md §10`
2. **Web app is Next.js** (App Router, TypeScript, Tailwind, shadcn/ui, TanStack Query, generated OpenAPI client, SSE live progress, wavesurfer.js). → `03-TRD.md §11`
3. **Built for others to adopt:** `docker compose up`, Python SDK + CLI, `pareeksha.yaml`, GitHub Action, agent adapters (`audio_v1` + Pipecat Must; LiveKit Should; Vapi Could), API keys. → `10-integrations-and-dx.md`
4. **Integrations:** plugin connector framework; v1 = Generic Webhook (source + sink, HMAC) and HubSpot sink. Salesforce, Zoho, LeadSquared, Freshdesk, Exotel, Slack are designed for, not built. → `10-integrations-and-dx.md §1–2`

## 2. Team hierarchy

```
Preetham (Human owner — approves, provides keys, recordings, labels, demo)
└── Orchestrator
    ├── Product Manager (PM)
    ├── Project Manager (PJM)
    ├── Tech Lead / Architect (TL)
    │   ├── Backend Core & API Engineer (BE-API)
    │   ├── Streaming & Infra Engineer (BE-INFRA)
    │   ├── Voice & Audio Engineer (VOICE)
    │   ├── Evaluation & ML Engineer (EVAL)
    │   ├── Integrations & DX Engineer (INT)
    │   └── Frontend Engineer (FE)
    ├── UI/UX Designer (DES)
    ├── QA & Test Engineer (QA)
    └── Technical Writer & DevRel (DOC)
```
Engineers report to TL; TL, PM, PJM, DES, QA and DOC report to the Orchestrator; the Orchestrator escalates to Preetham.

## 3. Roles

| Role | Owns | Key outputs |
|---|---|---|
| **Orchestrator** | Assignment & flow | Assigns tasks in dependency order, runs parallel work, merges only after QA passes, keeps `STATUS.md` current, escalates blockers > 2 h. Never writes product code. |
| **PM** | Scope | Must/Should/Won't list (PRD §7), acceptance criteria for any new task, demo storyline (PRD §9), rejects scope creep. |
| **PJM** | Time | Task board, critical path (§8), end-of-day report, triggers cut list (§10). |
| **TL** | Contracts & quality | Freezes contracts on Day 1 (§6) as code; reviews every PR against them; approves any later contract change (logged in `CHANGELOG.md`). |
| **BE-API** | `backend/pareeksha/api`, `db`, `runs`, `regression`, `schemas` | FastAPI routers, SQLAlchemy models, Alembic, outbox writes, SSE endpoint, API keys, OpenAPI quality. |
| **BE-INFRA** | `events/`, worker framework, `infra/`, Compose, CI | Kafka topics, producer, consumer framework (idempotency, retry, DLQ, shutdown), outbox relay, retrier, dlq-recorder, run-slot reconciler, CI. |
| **VOICE** | `gnani/`, `audio/`, `adapters/`, `simulation/`, `mock_agent/`, bot examples | Gnani wrappers, line simulator, caller pipeline, adapters, recording, mock EMI agent with 5 bugs. |
| **EVAL** | `llm/`, `evaluation/`, `audit/`, `dialect/` | Gemini client, prompts, metrics, checks, judge, scoring, calibration, audit pipeline, dialect report. |
| **INT** | `integrations/`, `sdk/`, `action/` | Connector framework, Webhook + HubSpot connectors, SSRF/HMAC helpers, SDK, CLI, `pareeksha.yaml`, GitHub Action. |
| **DES** | Design spec | IA, wireframe specs per page (Markdown + component lists), tokens (colour, type, spacing), score colour scale, empty/loading/error states. Hands to FE by end of Day 1. |
| **FE** | `web/` | Next.js app, BFF proxy, generated client, all pages, SSE, waveform call detail, heatmaps, integrations + DLQ pages. |
| **QA** | Tests & veto | Test plan, Kafka failure tests, contract tests, planted-bug test, Playwright smoke, final acceptance against PRD §8. Veto on merges. |
| **DOC** | `docs/`, README, guides | README, quick start (tested from clean clone), the 8 adopter guides (`10 §7`), SDK docs, demo script, launch post draft. |

## 4. Working rules (every agent)

1. Read the relevant doc sections and §6 contracts before starting a task.
2. Work only on your assigned task ID. Need something outside it → ask the Orchestrator.
3. Branch `task/<TASK-ID>-short-name`; one PR per task; PR lists task ID, what changed, how tested.
4. Never change a shared contract silently. Contract change = TL approval + `CHANGELOG.md` entry.
5. **Done** = code + tests passing + lint clean (ruff; eslint + tsc) + docs updated if behaviour changed + QA sign-off.
6. Secrets only from env. Never commit keys, real voices without consent, or real personal data. Fixtures are synthetic.
7. Blocked > 30 min → report to the Orchestrator with what you tried. **Don't guess vendor APIs: read the installed package source** (`gnani-vachana`, `pipecat-gnani`, `aiokafka`) or official docs.
8. Update `STATUS.md` when you start, block, or finish.
9. Stubs allowed to unblock others; mark `# STUB(<TASK-ID>)` and track them.
10. Every Kafka consumer uses the shared framework (`events/consumer.py`) — no hand-rolled poll loops.

## 5. Repo layout
See `docs/07-file-structure.md`. Ownership table there matches §3.

## 6. Frozen contracts (TL writes as code on Day 1)

### 6.1 Kafka topics & envelope
Exactly as `03-TRD.md §10.2–10.3` (topic names end in `.v1`). Notably:
- `pareeksha.call.requested.v1` is keyed by **run_item_id** (not run_id) so a run spreads across partitions and simulators.
- 6 partitions for work topics, RF 1 locally, retention 7 days, DLQ 30 days.
- Envelope: `event_id, type, version, occurred_at, correlation_id, causation_id, attempt, producer, payload`.
- Rules: offsets committed only after the DB commit; `processed_events` idempotency; retry.30s → retry.5m → DLQ after 3 attempts; throttled (run at cap) messages re-queue without consuming an attempt; all API-originated events go through the outbox; output event ids are deterministic (`uuid5(input_event_id, output_type)`).

### 6.2 REST API
`06-api-spec.md`. The OpenAPI document at `/openapi.json` is the contract for FE and the SDK; generated clients are checked in CI.

### 6.3 Connector interface
`10-integrations-and-dx.md §1.1` (`Connector` protocol, `AuditRequest`, `EvaluationSummary`), entry-point group `pareeksha.connectors`.

### 6.4 Agent session interface & audio protocol
`adapters/base.py` `AudioSession` (`send_pcm16`, `receive`, `close`) and `pareeksha-audio-v1` (`06-api-spec.md §7`).

### 6.5 Database
`docs/schema.sql` v0.2 = Alembic `0001_initial`.

## 7. Task board

Format: **ID** · Owner · Depends on · Done when.

### Day 1 — Sat 24 Oct: Contracts & foundations
- **H-01** · Preetham · — · Gnani + Gemini keys in `.env`; Timbre v3.0 access confirmed; Gemini model ID pinned; `SECRET_KEY` generated.
- **PM-01** · PM · — · Scope v0.2 confirmed against PRD §7 (Must/Should/Won't), acceptance criteria attached to every task below.
- **TL-01** · TL · PM-01 · §6 contracts committed as code: `events/topics.py`, `events/schemas.py`, `integrations/base.py`, `adapters/base.py`, FastAPI app with every route stubbed so `/openapi.json` is complete.
- **INFRA-01** · BE-INFRA · — · Compose from `docs/starter/` runs: Kafka (KRaft), kafka-init topics, Postgres, migrate, api, web placeholder, mock-agent placeholder. Image tags verified.
- **INFRA-02** · BE-INFRA · TL-01 · Consumer framework + producer + outbox relay + retrier + dlq-recorder, with tests for duplicate delivery, crash mid-handler, 3 failures → DLQ, throttle path.
- **API-01** · BE-API · TL-01 · SQLAlchemy models + Alembic `0001_initial` matching `schema.sql` v0.2; API-key auth dependency.
- **VOICE-01** · VOICE · H-01 · `scripts/smoke_gnani.py`: kn/hi TTS → STT round trip, stream STT, batch STT with diarization; voices auditioned; findings in `NOTES.md`; `COST_*` filled.
- **VOICE-02** · VOICE · — · Audio DSP + LineSimulator with 8 profiles; SNR ±0.5 dB, determinism and chunked==whole tests pass.
- **DES-01** · DES · PM-01 · IA + wireframe specs for every page in FR-DB-1, design tokens, score colour scale, component list, states.
- **FE-01** · FE · — · Next.js scaffold, Tailwind, shadcn/ui, layout + sidebar, BFF proxy route, `gen:api` script against TL-01's OpenAPI.
- **QA-01** · QA · PM-01 · Test plan mapping every FR/NFR to a test and owner.
- **DOC-01** · DOC · — · Docs pack v0.2 copied into `docs/`; README skeleton; `STATUS.md`, `CHANGELOG.md` created. *(Docs updates for the four changes are already done.)*

**Checkpoint (Preetham, end of Day 1):** approve TL-01 contracts and DES-01 designs.

### Day 2 — Sun 25 Oct: Core engines
- **API-02** · BE-API · API-01 · CRUD routers: agents, scenarios, personas, noise profiles, integrations, api-keys; seed script (20 personas, 8 profiles, rubric v1, mock agent, demo API key).
- **API-03** · BE-API · API-01, INFRA-02 · `POST /runs` writes run + outbox `run.requested`; `planner` consumer expands matrix and emits `call.requested` (key run_item_id); run-slot take/release + reconciler.
- **VOICE-03** · VOICE · VOICE-01 · Mock EMI agent over `pareeksha-audio-v1` with glass-box messages and 5 toggleable bugs.
- **VOICE-04** · VOICE · VOICE-02, VOICE-03, TL-01 · `audio_v1` adapter + caller pipeline: call tap, recorder, turn tracker, barge-in, end conditions.
- **EVAL-01** · EVAL · TL-01 · Gemini client (structured output, repair retry, usage logging); `caller_v1.j2`; caller brain wired into VOICE-04.
- **EVAL-02** · EVAL · — · Metrics, checks, Indian numeral parser, PII masking + unit tests.
- **INT-01** · INT · TL-01 · Connector registry (entry points), Fernet secrets, HMAC signing/verify, SSRF-safe fetch, Generic Webhook **sink** with delivery log.
- **FE-02** · FE · DES-01, FE-01 · Agents, Scenarios, Personas, Noise profiles pages (list + forms) on the generated client.
- **QA-02** · QA · INFRA-02 · Kafka integration suite green in CI (Testcontainers or Compose).

### Day 3 — Mon 26 Oct: Evaluation, audit, integrations
- **VOICE-05** · VOICE · VOICE-04, API-03 · `simulator` consumer: a 12-call run completes end to end with 3 simulator instances and per-run cap 3.
- **EVAL-03** · EVAL · EVAL-02 · `judge_v1.j2`, output schema, evidence validation, scoring in code; `evaluator` consumer; `finalizer` updates summaries and emits `run.completed`.
- **EVAL-04** · EVAL · EVAL-03 · `auditor` consumer: upload/import → batch STT (diarize, denoise) → role detection → `call.completed`.
- **INT-02** · INT · INT-01 · HubSpot sink: contact match (id/phone/email) → note; idempotent; built against `respx` mocks, then one live test with a free developer account.
- **INT-03** · INT · INT-01, EVAL-04 · Generic Webhook **source**: `POST /webhooks/inbound/{id}` verify → dedupe → import call → `audit.requested`.
- **API-04** · BE-API · API-03 · SSE `GET /runs/{id}/events` (from `pareeksha.progress.v1`), run compare, DLQ list/replay/discard, `/metrics/summary` (consumer lag, outbox backlog, DLQ count).
- **FE-03** · FE · FE-02, API-04 · Runs list, new-run wizard with cost estimate, live run detail (SSE), matrix heatmap.
- **QA-03** · QA · VOICE-05, EVAL-03 · Planted-bug test: ≥ 4 of 5 caught.

**Checkpoint (Preetham, end of Day 3):** watch one simulated call get scored live, and one HubSpot note appear from a webhook-imported call.

### Day 4 — Tue 27 Oct: Product complete
- **H-02** · Preetham · — · ≥ 20 consented clips per dialect group uploaded (start collecting on Day 1!).
- **EVAL-05** · EVAL · EVAL-03 · Dialect pipeline: normalisation, WER/CER, entity accuracy, intent, speaker-grouped bootstrap, HTML report.
- **VOICE-06** · VOICE · VOICE-04 · Pipecat adapter + `PareekshaFrameSerializer` + `examples/pipecat-bot` (Must); LiveKit adapter + example (Should); Vapi (Could).
- **INT-04** · INT · TL-01 · `pareeksha-sdk` + CLI (`login, apply, run, regress, audit, dlq, doctor`), `pareeksha.yaml`, GitHub Action with job summary.
- **API-05** · BE-API · EVAL-03 · Regression promote + suite runs; calibration endpoint; scenario generation (`generator` consumer + `scenario_drafts`).
- **FE-04** · FE · FE-03 · Call detail: waveform + regions, synced transcript, evidence-turn seeking, dimension scores, checks, promote dialog.
- **FE-05** · FE · FE-04 · Audits, Dialect heatmap, Regression, Integrations (add HubSpot/webhook, test, delivery log, redeliver), DLQ, Calibration, API keys pages.
- **QA-04** · QA · FE-04 · Playwright smoke per page; OpenAPI + event-schema contract tests; no API key in client bundles.

### Day 5 — Wed 28 Oct: Harden, demo, publish
- **QA-05** · QA · all · 40-call demo run + full acceptance vs PRD §8 (incl. duplicate/crash = no duplicate notes); P0/P1 bug list to Orchestrator by noon.
- **ALL-01** · engineers · QA-05 · Fix only QA's P0/P1 bugs.
- **EVAL-06** · EVAL + Preetham · QA-05 · Label 30 calls; publish κ and Spearman on the Calibration page.
- **DOC-02** · DOC · all · README, quick start tested from a clean clone, the 8 adopter guides, SDK reference.
- **DOC-03** · DOC + Preetham · QA-05 · 60-second demo script (PRD §9 incl. HubSpot note + GitHub Action); Preetham records.
- **PJM-01** · PJM · all · Release checklist: no secrets, no real PII, noise-clip licences, tag v1.0.0, repo public, launch post.

## 8. Critical path
H-01 → VOICE-01 → VOICE-03 → VOICE-04 → VOICE-05 → EVAL-03 → FE-04 → QA-05 → DOC-03.
Parallel critical chain: TL-01 → INFRA-02 → API-03 → VOICE-05.
If a critical-path task slips more than half a day, PJM invokes the cut list.

## 9. Human checkpoints (Preetham)
- Day 1: keys (H-01); approve contracts (TL-01) and designs (DES-01); start dialect clip collection.
- Day 3: watch a live scored call and a HubSpot note.
- Day 4: dialect clips (H-02).
- Day 5: label calls (EVAL-06), record the demo, approve release.

## 10. Cut list (cut from the top first)
1. Vapi adapter, then LiveKit adapter (keep `audio_v1` + Pipecat)
2. Run compare view
3. Scenario generation (write scenarios by hand)
4. Calibration page (compute κ in a notebook)
5. GitHub Action (keep CLI)
6. Generic Webhook source (keep HubSpot sink + webhook sink)

**Never cut:** mock agent with planted bugs, judge with evidence, Kafka outbox + idempotency + retry + DLQ, call detail page, dialect table, HubSpot sink, demo video.

## 11. STATUS.md template

```
| Task | Owner | State (todo/doing/blocked/review/done) | Branch | Notes |
```
End-of-day report (PJM): done today, blocked, critical-path status, credits used, consumer lag / DLQ count from `/metrics/summary`, tomorrow's first tasks.
