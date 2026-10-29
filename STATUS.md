# STATUS.md — Pareeksha build board

Kept current by the Orchestrator and PJM. Every agent updates its row when it starts, blocks or finishes a task. Task details: `docs/AGENTS.md §7`.

**Today:** Day 1 · Sat 24 Oct 2026 · Critical path: H-01 → VOICE-01 · Parallel chain: TL-01 → INFRA-02 → API-03 → VOICE-05

State values: todo / doing / blocked / review / done. Verified = QA sign-off (`yes` / `no`).

## Task board

| ID | Title | Role | Depends on | State | Owner | Verified |
|---|---|---|---|---|---|---|
| H-01 | Keys in `.env`, Timbre v3.0 access, Gemini model ID, SECRET_KEY | Preetham (human) | — | keys in cloud env (Gnani, DeepSeek, Gemini) — usable only in new cloud sessions; key-dependent tasks run as separate sessions | — | no |
| PM-01 | Scope v0.2 vs PRD §7; acceptance criteria per task | PM | — | done | — | proof/PM-01/verified.md |
| TL-01 | Freeze §6 contracts as code; full OpenAPI stubs | TL | PM-01 | done | — | proof/TL-01/verified.md |
| INFRA-01 | Compose from `docs/starter/` runs (Kafka KRaft, Postgres, topics) | BE-INFRA | — | done | — | proof/INFRA-01/verified.md |
| INFRA-02 | Consumer framework, producer, outbox relay, retrier, DLQ recorder | BE-INFRA | TL-01 | done | — | proof/INFRA-02/verified.md |
| API-01 | SQLAlchemy models, Alembic `0001_initial`, API-key auth | BE-API | TL-01 | done | — | proof/API-01/verified.md |
| VOICE-01 | `scripts/smoke_gnani.py`: TTS/STT round trip, voices, `COST_*` | VOICE | H-01 | done | — | proof/VOICE-01/verified.md |
| VOICE-02 | Audio DSP + LineSimulator (8 profiles) | VOICE | — | done | — | proof/VOICE-02/verified.md |
| DES-01 | IA, wireframe specs, tokens, score scale, states | DES | PM-01 | done | — | proof/DES-01/verified.md |
| FE-01 | Next.js scaffold, Tailwind, shadcn/ui, BFF proxy, `gen:api` | FE | — | done | — | proof/FE-01/verified.md |
| QA-01 | Test plan mapping every FR/NFR to a test | QA | PM-01 | done | — | proof/QA-01/verified.md |
| DOC-01 | Docs pack in `docs/`, README skeleton, STATUS, CHANGELOG | DOC | — | done | — | proof/DOC-01/verified.md |
| API-02 | CRUD routers + seed script (personas, profiles, rubric, demo key) | BE-API | API-01 | done | — | proof/API-02/verified.md |
| API-03 | `POST /runs` outbox + planner + run-slot reconciler | BE-API | API-01, INFRA-02 | done | — | proof/API-03/verified.md |
| VOICE-03 | Mock EMI agent over `pareeksha-audio-v1` with 5 bugs | VOICE | VOICE-01 | done | — | proof/VOICE-03/verified.md |
| VOICE-04 | `audio_v1` adapter + caller pipeline | VOICE | VOICE-02, VOICE-03, TL-01 | done | — | proof/VOICE-04/verified.md |
| EVAL-01 | Gemini client, `caller_v1.j2`, caller brain wiring | EVAL | TL-01 | done | — | proof/EVAL-01/verified.md |
| EVAL-02 | Metrics, checks, Indian numeral parser, PII masking | EVAL | — | done | — | proof/EVAL-02/verified.md |
| INT-01 | Connector registry, Fernet, HMAC, SSRF-safe fetch, webhook sink | INT | TL-01 | done | — | proof/INT-01/verified.md |
| FE-02 | Agents, Scenarios, Personas, Noise profiles pages | FE | DES-01, FE-01 | done | — | proof/FE-02/verified.md |
| QA-02 | Kafka integration suite green in CI | QA | INFRA-02 | done (local CI-equivalent run; GitHub Actions green link pending) | — | proof/QA-02/verified.md |
| VOICE-05 | `simulator` consumer; 12-call run end to end | VOICE | VOICE-04, API-03 | done | — | proof/VOICE-05/verified.md |
| EVAL-03 | `judge_v1.j2`, evidence validation, `evaluator`, `finalizer` | EVAL | EVAL-02 | done | — | proof/EVAL-03/verified.md |
| EVAL-04 | `auditor` consumer: upload → batch STT → role detection | EVAL | EVAL-03 | done | — | proof/EVAL-04/verified.md |
| INT-02 | HubSpot sink: contact match → note, idempotent | INT | INT-01 | done (live HubSpot note pending owner token) | — | proof/INT-02/verified.md |
| INT-03 | Generic Webhook source: verify → dedupe → audit | INT | INT-01, EVAL-04 | done (live HubSpot step pending owner token) | — | proof/INT-03/verified.md |
| API-04 | SSE progress, run compare, DLQ endpoints, `/metrics/summary` | BE-API | API-03 | done | — | proof/API-04/verified.md |
| FE-03 | Runs list, new-run wizard, live run detail (SSE), heatmap | FE | FE-02, API-04 | done | — | proof/FE-03/verified.md |
| QA-03 | Planted-bug test: at least 4 of 5 caught | QA | VOICE-05, EVAL-03 | done | — | proof/QA-03/verified.md |
| H-02 | ≥ 20 consented clips per dialect group | Preetham (human) | — | waiting on Preetham | — | no |
| EVAL-05 | Dialect pipeline: WER/CER, entity accuracy, HTML report | EVAL | EVAL-03 | done (real dialect clips pending H-02) | — | proof/EVAL-05/verified.md |
| VOICE-06 | Pipecat adapter + serializer + example (Must); LiveKit (Should) | VOICE | VOICE-04 | done (LiveKit/Vapi cut by owner 2026-10-28, see CHANGELOG) | — | proof/VOICE-06/verified.md |
| INT-04 | `pareeksha-sdk` + CLI, `pareeksha.yaml`, GitHub Action | INT | TL-01 | done | — | proof/INT-04/verified.md |
| API-05 | Regression promote/suite, calibration, scenario generation | BE-API | EVAL-03 | done | — | proof/API-05/verified.md |
| FE-04 | Call detail: waveform, transcript, evidence seeking, promote | FE | FE-03 | done | — | proof/FE-04/verified.md |
| FE-05 | Audits, Dialect, Regression, Integrations, DLQ, Calibration, API keys | FE | FE-04 | done | — | proof/FE-05/verified.md |
| QA-04 | Playwright smoke per page; OpenAPI + event contract tests | QA | FE-04 | done | — | proof/QA-04/verified.md |
| QA-05 | 40-call demo run + full PRD §8 acceptance | QA | all | done | — | proof/QA-05/verified.md |
| ALL-01 | Fix QA P0/P1 bugs only | engineers | QA-05 | todo | — | no |
| EVAL-06 | Label 30 calls; publish κ and Spearman | EVAL + Preetham | QA-05 | todo | — | no |
| DOC-02 | README, clean-clone quick start, 8 adopter guides, SDK reference | DOC | all | done | — | proof/DOC-02/verified.md |
| DOC-03 | 60-second demo script; Preetham records | DOC + Preetham | QA-05 | todo | — | no |
| PJM-01 | Release checklist, tag v1.0.0, repo public, launch post | PJM | all | todo | — | no |

Notes: PM-01 issue: FR-RN-2 cost estimate is Should but required by FE-03; F19 per-run HTML export (Could) and Vapi have no board task.

Ready now (no dependencies): H-01, PM-01, INFRA-01, VOICE-02, FE-01, DOC-01, EVAL-02, H-02.

- TL-01 scope widened: includes DeepSeek LLM provider interface, plus pyproject + mypy.
- VOICE-02: noise synthesized in code, not data/noise clips (TRD §6) — licence check under PJM-01; profiles in audio/profiles.py, API-02 seed must load these (rubric §7 names YAML).
- Decision 2026-10-23 (Preetham): DeepSeek default LLM, Gemini optional.
- No type checker configured yet — TL-01 adds mypy.

## Escalations
- None.

## Credit use (Gnani/Gemini)
- Budget (`BUDGET_CREDITS`, from `.env.example`): 5000 (default, not yet confirmed).
- Used today / total: 0 / 0. `COST_*` values not yet measured (VOICE-01).

## Open STUBs
| Marker | Owner | Replace by task |
|---|---|---|
| `STUB(TL-01)` `backend/pareeksha/api/main.py` | TL | TL-01 |
| `STUB(VOICE-03)` `mock_agent/server.py` | VOICE | VOICE-03 |
| `STUB(FE-01)` `web/Dockerfile` | FE | FE-01 |
| `STUB(API-01)` `backend/alembic_migrate.sh` | BE-API | API-01 |
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

## Budget & verification policy (owner, 2026-10-23)
- Total cloud credit budget: $100 (owner revised 2026-10-23; be careful, owner reviews if exceeded). Spent ≈ $13 at 18:50 UTC (batch 1: 7 tasks built, 5 verified).
- Verification is batched at milestones (after a major build), not per task: M1 foundation (TL-01, QA-01, DES-01, FE-01, VOICE-01) → M2 pipeline end-to-end → M3 UI + integrations → M4 final `make verify`.

## M1 (foundation) — merged 2026-10-24
- Verified: TL-01, QA-01, DES-01, FE-01 (qa batch), VOICE-01 (separate cloud verifier). Integration fix (ruff format/E731/mypy) task/M1-fix f406d67, re-checked: 540 passed, 0 skipped, 97% cov; ruff, mypy, web lint/typecheck clean.
- Owner approved TL-01 contracts 2026-10-24 ("Continue"); contracts frozen.
- Gnani credit use: VOICE-01 build 17 calls (23.3 s TTS, 67 s STT); verify 11 calls (23.4 s TTS, 33.6 s STT).
- Follow-ups: add gnani-vachana to backend dev deps; VOICE voices chosen by STT only (Preetham to listen); HubSpot token (HUBSPOT_ACCESS_TOKEN) needed for INT-*.
- Open STUBs now: api/stubs.py handlers owned by API-02..05, EVAL-04/05, INT-01/03, VOICE-04; STUB(API-01) auth; STUB(VOICE-03) mock_agent; STUB(FE-02/03/05) pages.

## Release candidate — merged 2026-10-28 (qa/RC2 17c51b9)
- Independent verification: 41 task proofs signed (incl. EVAL-03b, EVAL-04b, INT-01b, FIX-01, VOICE-07). FE-03 now verified (Run compare built, qa/FE-03b d8b92f2, 2026-10-28).
- make verify: V2 PASS (156 s warm, 1581 s cold cache pulls), V3 97.5% (QA-03 run 8422cb13), V4 PASS (5/5), V6 PASS (1 delivery, 1 evaluation). V1 FAIL (unfinished owner tasks + FE-03), V11 FAIL (no tag/public repo). V5/V7/V8/V9/V10 PENDING owner inputs.
- UI review: 17/17 pages pass (Run compare PASS with 8 minor non-blocking fixes listed).
- NOT DONE (owner-blocked): H-02 dialect clips, EVAL-06 (30 labels), DOC-03 demo, PJM-01 release (public repo + v1.0.0), ALL-01, HubSpot token, provider keys, GitHub Actions run links (V8).
- Known caveats: clean pass rate not fully deterministic (V4 control 2/2 one run, 1/2 another); Gnani allows one concurrent request per key.

## GOAL item 8 — GitHub Action regression gate (2026-10-29)
- PR voice-application/pareeksha-#1 (planted bug `no_disclosure` ON): `suite` FAILED with a judged verdict — 1/1 call evaluated, pass rate 0.0% < 80%, 0 infra errors. Run: https://github.com/Voice-Application/Pareeksha-/actions/runs/40894601670
- PR voice-application/pareeksha-#2 (bug removed): `suite` PASSED, plus backend/web/sdk/kafka/build-fail-grep all green on ea08f12. Run: https://github.com/Voice-Application/Pareeksha-/actions/runs/40894620111
- Fix that made CI reliable: task/FIX-CI (speech retry on retryable errors, regression workflow concurrency group, personas filter race fix) — merged here.
- Live HubSpot acceptance (GOAL item 5/6/10) evidence on task/LIVE-ACCEPT (note 412826916601, 9.1 s) — pending independent verification in the final make verify.
