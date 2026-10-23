# STATUS.md — Pareeksha build board

Kept current by the Orchestrator and PJM. Every agent updates its row when it starts, blocks or finishes a task. Task details: `docs/AGENTS.md §7`.

**Today:** Day 1 · Sat 24 Oct 2026 · Critical path: H-01 → VOICE-01 · Parallel chain: TL-01 → INFRA-02 → API-03 → VOICE-05

State values: todo / doing / blocked / review / done. Verified = QA sign-off (`yes` / `no`).

## Task board

| ID | Title | Role | Depends on | State | Owner | Verified |
|---|---|---|---|---|---|---|
| H-01 | Keys in `.env`, Timbre v3.0 access, Gemini model ID, SECRET_KEY | Preetham (human) | — | waiting on Preetham | — | no |
| PM-01 | Scope v0.2 vs PRD §7; acceptance criteria per task | PM | — | done | — | proof/PM-01/verified.md |
| TL-01 | Freeze §6 contracts as code; full OpenAPI stubs | TL | PM-01 | doing | — | no |
| INFRA-01 | Compose from `docs/starter/` runs (Kafka KRaft, Postgres, topics) | BE-INFRA | — | doing | — | no |
| INFRA-02 | Consumer framework, producer, outbox relay, retrier, DLQ recorder | BE-INFRA | TL-01 | todo | — | no |
| API-01 | SQLAlchemy models, Alembic `0001_initial`, API-key auth | BE-API | TL-01 | todo | — | no |
| VOICE-01 | `scripts/smoke_gnani.py`: TTS/STT round trip, voices, `COST_*` | VOICE | H-01 | todo | — | no |
| VOICE-02 | Audio DSP + LineSimulator (8 profiles) | VOICE | — | doing | — | no |
| DES-01 | IA, wireframe specs, tokens, score scale, states | DES | PM-01 | doing | — | no |
| FE-01 | Next.js scaffold, Tailwind, shadcn/ui, BFF proxy, `gen:api` | FE | — | doing | — | no |
| QA-01 | Test plan mapping every FR/NFR to a test | QA | PM-01 | todo | — | no |
| DOC-01 | Docs pack in `docs/`, README skeleton, STATUS, CHANGELOG | DOC | — | done | — | proof/DOC-01/verified.md |
| API-02 | CRUD routers + seed script (personas, profiles, rubric, demo key) | BE-API | API-01 | todo | — | no |
| API-03 | `POST /runs` outbox + planner + run-slot reconciler | BE-API | API-01, INFRA-02 | todo | — | no |
| VOICE-03 | Mock EMI agent over `pareeksha-audio-v1` with 5 bugs | VOICE | VOICE-01 | todo | — | no |
| VOICE-04 | `audio_v1` adapter + caller pipeline | VOICE | VOICE-02, VOICE-03, TL-01 | todo | — | no |
| EVAL-01 | Gemini client, `caller_v1.j2`, caller brain wiring | EVAL | TL-01 | todo | — | no |
| EVAL-02 | Metrics, checks, Indian numeral parser, PII masking | EVAL | — | doing | — | no |
| INT-01 | Connector registry, Fernet, HMAC, SSRF-safe fetch, webhook sink | INT | TL-01 | todo | — | no |
| FE-02 | Agents, Scenarios, Personas, Noise profiles pages | FE | DES-01, FE-01 | todo | — | no |
| QA-02 | Kafka integration suite green in CI | QA | INFRA-02 | todo | — | no |
| VOICE-05 | `simulator` consumer; 12-call run end to end | VOICE | VOICE-04, API-03 | todo | — | no |
| EVAL-03 | `judge_v1.j2`, evidence validation, `evaluator`, `finalizer` | EVAL | EVAL-02 | todo | — | no |
| EVAL-04 | `auditor` consumer: upload → batch STT → role detection | EVAL | EVAL-03 | todo | — | no |
| INT-02 | HubSpot sink: contact match → note, idempotent | INT | INT-01 | todo | — | no |
| INT-03 | Generic Webhook source: verify → dedupe → audit | INT | INT-01, EVAL-04 | todo | — | no |
| API-04 | SSE progress, run compare, DLQ endpoints, `/metrics/summary` | BE-API | API-03 | todo | — | no |
| FE-03 | Runs list, new-run wizard, live run detail (SSE), heatmap | FE | FE-02, API-04 | todo | — | no |
| QA-03 | Planted-bug test: at least 4 of 5 caught | QA | VOICE-05, EVAL-03 | todo | — | no |
| H-02 | ≥ 20 consented clips per dialect group | Preetham (human) | — | waiting on Preetham | — | no |
| EVAL-05 | Dialect pipeline: WER/CER, entity accuracy, HTML report | EVAL | EVAL-03 | todo | — | no |
| VOICE-06 | Pipecat adapter + serializer + example (Must); LiveKit (Should) | VOICE | VOICE-04 | todo | — | no |
| INT-04 | `pareeksha-sdk` + CLI, `pareeksha.yaml`, GitHub Action | INT | TL-01 | todo | — | no |
| API-05 | Regression promote/suite, calibration, scenario generation | BE-API | EVAL-03 | todo | — | no |
| FE-04 | Call detail: waveform, transcript, evidence seeking, promote | FE | FE-03 | todo | — | no |
| FE-05 | Audits, Dialect, Regression, Integrations, DLQ, Calibration, API keys | FE | FE-04 | todo | — | no |
| QA-04 | Playwright smoke per page; OpenAPI + event contract tests | QA | FE-04 | todo | — | no |
| QA-05 | 40-call demo run + full PRD §8 acceptance | QA | all | todo | — | no |
| ALL-01 | Fix QA P0/P1 bugs only | engineers | QA-05 | todo | — | no |
| EVAL-06 | Label 30 calls; publish κ and Spearman | EVAL + Preetham | QA-05 | todo | — | no |
| DOC-02 | README, clean-clone quick start, 8 adopter guides, SDK reference | DOC | all | todo | — | no |
| DOC-03 | 60-second demo script; Preetham records | DOC + Preetham | QA-05 | todo | — | no |
| PJM-01 | Release checklist, tag v1.0.0, repo public, launch post | PJM | all | todo | — | no |

Notes: PM-01 issue: FR-RN-2 cost estimate is Should but required by FE-03; F19 per-run HTML export (Could) and Vapi have no board task.

Ready now (no dependencies): H-01, PM-01, INFRA-01, VOICE-02, FE-01, DOC-01, EVAL-02, H-02.

## Escalations
- None.

## Credit use (Gnani/Gemini)
- Budget (`BUDGET_CREDITS`, from `.env.example`): 5000 (default, not yet confirmed).
- Used today / total: 0 / 0. `COST_*` values not yet measured (VOICE-01).

## Open STUBs
| Marker | Owner | Replace by task |
|---|---|---|
Open STUBs note: TL-01 will introduce STUB(<owner-task>) markers on API route bodies, removed by owning tasks.

## Cuts (need owner approval)
Proposed cut order from `docs/AGENTS.md §10`, not yet approved by Preetham. Nothing is cut.
1. Vapi adapter, then LiveKit adapter
2. Run compare view
3. Scenario generation
4. Calibration page
5. GitHub Action
6. Generic Webhook source

Never cut: mock agent with planted bugs, judge with evidence, Kafka outbox + idempotency + retry + DLQ, call detail page, dialect table, HubSpot sink, demo video.

## End-of-day report
- Done today:
- Blocked:
- Critical path status:
- Credits used (today / total):
- Consumer lag / open DLQ:
- Tomorrow's first tasks:
