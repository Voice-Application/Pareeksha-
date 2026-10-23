# SCOPE v0.2 (PM-01)

Confirmed against `01-PRD.md` §7 on 24 Oct 2026. Requirement IDs refer to `02-requirements.md`; "PRD §8" metrics are the release gate. QA verifies each task against its criteria below. Anything not listed here is rejected as scope creep unless the PM adds it with criteria.

## 1. Must / Should / Could / Won't (PRD §7, unchanged)

| Priority | Features |
|---|---|
| Must | F1 Agent registry, F2 Scenarios, F3 Personas (20 seed), F4 Noise profiles (8), F5 Simulated caller, F6 Kafka run orchestration, F7 Recording, F8 Deterministic metrics, F9 Gemini judge with evidence, F10 Post-call audit, F11 Dialect ASR report, F12 Next.js app, F13 Mock EMI agent (5 bugs), F22 Connector framework, F23 Webhook connector, F24 HubSpot sink, F25 SDK + CLI, F26 `audio_v1` + Pipecat adapters, F28 API keys |
| Should | F14 Regression promote/re-run, F15 Run compare, F16 Human review + kappa, F17 Cost tracking, F18 Glass-box mode, F20 GitHub Action, F26 LiveKit, F27 `pareeksha.yaml`, F29 DLQ viewer/replay |
| Could | F19 HTML report per run, F26 Vapi |
| Won't (v1) | F21 PSTN/SIP, live monitoring, multi-tenant auth. F30 Salesforce, Zoho, LeadSquared, Freshdesk, Exotel, Slack connectors (designed for only) |

Never cut (AGENTS §10): mock agent with planted bugs, judge with evidence, Kafka outbox + idempotency + retry + DLQ, call detail page, dialect table, HubSpot sink, demo video.

Scope notes (priorities unchanged):
- FE-03 shows a cost estimate in the new-run wizard although FR-RN-2 is Should; it is the first part dropped if FE-03 slips.
- EVAL-05's HTML report is the dialect report (F11, Must). The per-run HTML export (F19) stays Could and has no board task.
- Vapi (Could) has no task beyond the optional clause of VOICE-06; LiveKit is Should.

## 2. Acceptance criteria per task

Every task also needs AGENTS §4.5 (tests pass, ruff/eslint/tsc clean, docs updated) and a proof folder. Below is the task-specific part.

### Day 1
- **H-01**: `.env` holds Gnani and Gemini keys and a generated `SECRET_KEY`; a real Timbre v3.0 TTS call succeeds; Gemini model ID pinned in `.env.example` and NOTES.md. (A-2)
- **PM-01**: this file exists and every task in AGENTS §7 has criteria here.
- **TL-01**: §6 contracts exist as code; `GET /openapi.json` lists every route in `06-api-spec.md`; event schemas validate sample payloads; later contract changes are logged in CHANGELOG. (FR-DB-6 basis)
- **INFRA-01**: `docker compose up` brings Kafka (KRaft), the 12 topics, Postgres, migrate, api, web and mock-agent placeholders to healthy; `create-topics.sh` is idempotent on a second run. (NFR-11, FR-DX-1 partial)
- **INFRA-02**: tests show duplicate delivery gives one side effect, a crash mid-handler redelivers once, 3 failures land in the DLQ via `retry.30s` then `retry.5m`, the throttle path works; offsets commit after the DB commit. (FR-RN-9, NFR-4, NFR-4c)
- **API-01**: Alembic `0001_initial` yields tables matching `schema.sql`; API keys stored hashed, scope check rejects insufficient scope, key shown once. (FR-DX-2, NFR-15)
- **VOICE-01**: `scripts/smoke_gnani.py` runs kn and hi TTS to STT round trips, stream STT and batch STT with diarization; findings and `COST_*` recorded in NOTES.md; chosen voices recorded. (C-1, A-2, FR-CO-1)
- **VOICE-02**: 8 profiles render distinct audio; SNR within ±0.5 dB; same seed gives byte-identical output; chunked equals whole. (FR-NP-1..4, NFR-5)
- **DES-01**: a spec for every FR-DB-1 page with empty/loading/error states, tokens, score colour scale and component list; approved at the Day 1 checkpoint.
- **FE-01**: `npm run build`, eslint and tsc pass; sidebar layout renders; BFF route proxies without exposing the key; `gen:api` produces `schema.d.ts` from TL-01. (FR-DB-5, FR-DB-6)
- **QA-01**: a table maps every FR/NFR and each PRD §8 metric to a test, level and owner; no ID unmapped.
- **DOC-01**: docs pack in `docs/`, README, STATUS and CHANGELOG present with working links.

### Day 2
- **API-02**: CRUD for agents, scenarios, personas, noise profiles, integrations, api-keys per `06-api-spec.md`; seed creates 20 personas (>=6 Kannada/Kanglish, >=6 Hindi/Hinglish, >=4 Indian English), 8 profiles, rubric v1, mock agent, demo key; seed is idempotent. (FR-AG-1/2, FR-SC-1/3/4, FR-PE-1/2, FR-NP-1/2, FR-IN-2)
- **API-03**: `POST /runs` writes run and outbox row in one transaction; planner expands the matrix with `call.requested` keyed by run_item_id; run slots never exceed the per-run cap and the reconciler repairs a leaked slot. (FR-RN-1, FR-RN-3, NFR-4b)
- **VOICE-03**: mock agent speaks `pareeksha-audio-v1`, sends glass-box messages, and each of the 5 bugs in FR-MK-3 toggles independently. (FR-MK-1..3)
- **VOICE-04**: adapter and caller pipeline produce caller, agent and mixed recordings (16 kHz mono tracks, stereo mix), per-turn records, barge-in at 0.8-2.5 s and all end conditions; loopback overhead <= 50 ms. (FR-RN-4..8, FR-DX-7 audio_v1, NFR-2)
- **EVAL-01**: Gemini client returns schema-valid JSON, does one repair retry and logs usage; `caller_v1.j2` produces persona-language utterances; first utterance reproducible for the same seed. (NFR-5, FR-CO-1)
- **EVAL-02**: unit tests for latency/barge-in/silence/talk-ratio metrics, disclosure and forbidden-phrase checks, Indian numeral parser (e.g. "naal-ku saavira" = 4000), PII masking of phone/Aadhaar/PAN; coverage >= 70% on `evaluation/`. (FR-EV-1/2/9, NFR-9, NFR-12)
- **INT-01**: connectors discovered by entry point; secrets Fernet-encrypted and never returned; HMAC verify rejects bad signature and stale timestamp; SSRF guard blocks private ranges; webhook sink logs deliveries and is idempotent per (integration, event). (FR-IN-1/2/5/6/9, NFR-15)
- **FE-02**: four list+form pages work against the generated client with all three states; no key in the bundle. (FR-DB-1, FR-DB-5)
- **QA-02**: Kafka suite (duplicate, crash, DLQ, Kafka-down outbox drain in order) green in CI. (NFR-4, NFR-4b)

### Day 3
- **VOICE-05**: a 12-call run completes with 3 simulator instances and per-run cap 3 (never more than 3 active); >= 95% of calls finish without infra error against the mock agent. (FR-RN-3/4, NFR-3, NFR-4c)
- **EVAL-03**: judge at temperature 0 with pinned model scores 7 dimensions 0-4 with evidence turn indices validated against the transcript; score computed in code (pass >= 80 and no critical failure); critical failure or failed disclosure sets `needs_human_review`; each evaluation stores rubric version, prompt hash, model ID, tokens; finalizer emits `run.completed` once. (FR-EV-3..6, NFR-6, NFR-7)
- **EVAL-04**: uploaded WAV/MP3 (<= 10 MB) goes through batch STT with diarization and denoise, agent speaker detected (user override allowed), then `call.completed`. (FR-AU-1..4)
- **INT-02**: HubSpot sink matches contact by id, phone or email and creates one note; replay creates no second note; bad token gives a clear error; unit tests on `respx`, one live test on a developer account. (FR-IN-3/5/8, PRD §8 zero duplicate notes)
- **INT-03**: signed webhook with an import URL becomes a call and `audit.requested`; bad signature or replayed delivery is rejected/deduped; unsafe URLs refused. (FR-IN-7, NFR-15)
- **API-04**: SSE streams run progress and survives reconnect; compare returns per-cell deltas; DLQ list/replay/discard work; `/metrics/summary` shows lag, outbox backlog and DLQ count. (FR-RG-3, FR-IN-10, NFR-16)
- **FE-03**: wizard shows matrix size and cost estimate; run detail updates live via SSE; heatmap cells link to calls. (FR-RN-1/2, FR-DB-1/2)
- **QA-03**: with all 5 bugs on, the run flags >= 4 of 5 (PRD §8); with bugs off the pass rate is high. (FR-MK-3)

### Day 4
- **H-02**: >= 20 clips each for >= 3 Kannada dialect groups, Hindi and code-mixed, all with consent flag and reference text. (PRD §8, NFR-9)
- **EVAL-05**: manifest import, three conditions (clean 16k, PSTN 8k A-law, PSTN + noise), normalised WER/CER, entity accuracy, intent, speaker-grouped bootstrap CI, bias_list suggestions, HTML report; consent flag enforced. (FR-DI-1..4, FR-DI-6)
- **VOICE-06**: Pipecat adapter with `PareekshaFrameSerializer` and `examples/pipecat-bot` completes a test call (Must); LiveKit example (Should, cut first). (FR-DX-7, FR-DX-8)
- **INT-04**: SDK (sync + async) and CLI (`login, apply, run, regress, audit, dlq, doctor`) exit non-zero on failure; `apply` twice changes nothing; GitHub Action writes a job summary and fails the check on regression. (FR-DX-3..6, FR-RG-4)
- **API-05**: promote creates a `blocking` regression test from a failed call; suite run fails if any blocking test fails; calibration returns kappa and Spearman; `generator` yields N valid scenario drafts. (FR-RG-1/2, FR-AU-5, FR-EV-8, FR-SC-2)
- **FE-04**: waveform with regions, transcript synced to audio, evidence turns seek, dimension scores, checks, promote dialog, human review form. (FR-DB-3, FR-EV-7)
- **FE-05**: remaining FR-DB-1 pages: Audits, Dialect heatmap with metric selector, Regression, Integrations (test, delivery log, redeliver), DLQ, Calibration, API keys. (FR-DB-4, FR-IN-9/10, FR-DX-2)
- **QA-04**: Playwright smoke visits every page; OpenAPI and event-schema contract tests pass; bundle scan finds no API key. (FR-DB-5, FR-DB-6)

### Day 5
- **QA-05**: 40-call demo run (5 x 4 x 2) completes; every PRD §8 product metric measured and reported pass/fail; duplicate delivery and worker crash give zero duplicate evaluations or CRM notes; P0/P1 list to Orchestrator by noon. (PRD §8, NFR-1, NFR-3, NFR-4)
- **ALL-01**: only QA's P0/P1 items fixed, each with a regression test; no new features.
- **EVAL-06**: 30 calls labelled by Preetham; kappa and Spearman published on the Calibration page; if kappa < 0.6 the rubric is bumped and recalibrated. (PRD §8, FR-EV-8)
- **DOC-02**: a person follows the README from a clean clone to a first evaluated call in < 20 min; 8 adopter guides (`10 §7`) and SDK reference exist; README has architecture diagram, a real dialect heatmap and honest limitations. (NFR-14, FR-DX-10)
- **DOC-03**: 60-second script follows PRD §9 steps 1-8 including the HubSpot note and GitHub Action; Preetham records. (PRD §8 portfolio)
- **PJM-01**: checklist signed: no secrets, no real PII, noise-clip licences cleared, tag v1.0.0, repo public, launch post drafted.

## 3. Demo storyline
Fixed as PRD §9 (8 steps). A feature not needed by a demo step or a PRD §8 metric is next to be cut after the AGENTS §10 list.
