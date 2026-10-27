# 02 — Requirements Specification

Every requirement has an ID, a priority (**M**ust / **S**hould / **C**ould) and an acceptance test. Feature IDs (F1…) refer to the PRD.

**v0.2 changes:** queueing requirements now target Kafka (§1.5, NFR-4); the dashboard is a Next.js web app (§1.10); new §1.13 Integrations and §1.14 Developer experience.

---

## 1. Functional requirements

### 1.1 Agent registry (F1)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-AG-1 | User can create, edit, list and archive agents. | M | CRUD via API and dashboard; archived agents hidden from run creation. |
| FR-AG-2 | An agent stores: name, adapter (`audio_v1`, `pipecat`, `livekit`, `vapi`), endpoint URL, adapter config, primary language(s), description/system prompt text, mandatory disclosures (list of phrases or regex), forbidden phrases, expected tools, max call duration. | M | All fields persisted and returned by `GET /agents/{id}`. |
| FR-AG-3 | "Test connection" button opens the WebSocket, sends 1 s of silence, and confirms the agent speaks within 10 s. | M | Returns `ok` + measured first-audio latency, or a clear error (DNS, refused, timeout, protocol). |
| FR-AG-4 | Agent can declare `glass_box: true`, meaning it sends transcript/tool-call control messages over the socket. | S | When true, the platform stores agent-reported transcripts and tool calls per turn. |

### 1.2 Scenarios (F2)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-SC-1 | User can create a scenario with: title, caller goal, background facts (fixtures), success criteria (plain language), expected tool calls (optional), must-say / must-not-say rules, tags, max turns. | M | Saved and editable. |
| FR-SC-2 | Platform can generate N scenarios from an agent's description using Gemini, covering happy path, edge cases and adversarial cases. | M | Given an agent, generating 10 scenarios returns 10 valid scenario objects that pass schema validation; user reviews before saving. |
| FR-SC-3 | Scenarios are language-independent; the persona decides the language. | M | Same scenario runs with a Kannada and a Hindi persona without edits. |
| FR-SC-4 | Scenario has a `source` field: `manual`, `generated`, or `promoted` (from a call). | M | Promoted scenarios link to their source call. |

### 1.3 Personas (F3)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-PE-1 | Persona fields: name, language code, code-mix style (`none`, `light`, `heavy`), dialect label (descriptive only), TTS model, voice ID, speaking speed, emotion, patience (turns before giving up), interruption level (0–3), silence habit, behaviour notes. | M | Schema-validated. |
| FR-PE-2 | Ship 20 seed personas: ≥ 6 Kannada/Kanglish, ≥ 6 Hindi/Hinglish, ≥ 4 Indian English, plus elderly-slow, interrupter, silent, abusive-but-safe, confused. | M | Seed script loads all 20. |
| FR-PE-3 | Persona preview: synthesise one sample line with its voice and settings. | S | Audio plays in dashboard. |

### 1.4 Noise profiles (F4)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-NP-1 | Noise profile fields: name, sample rate, codec (`none`, `mulaw`, `alaw`), PSTN bandpass on/off, background category, SNR (dB), packet-loss %, clipping on/off. | M | Schema-validated. |
| FR-NP-2 | Ship 8 named profiles (see rubric doc §7). | M | All 8 render audible, distinct output on a sample clip. |
| FR-NP-3 | Noise is mixed at the requested SNR with ±0.5 dB accuracy. | M | Unit test measures SNR of mixed output. |
| FR-NP-4 | Same seed → identical noisy audio. | M | Two runs with the same seed produce byte-identical output. |

### 1.5 Simulated caller and run orchestration (F5, F6, F7)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-RN-1 | User creates a run by selecting an agent, scenarios, personas and noise profiles; the platform expands the full matrix into run items. | M | 3 scenarios × 2 personas × 2 profiles creates 12 run items. |
| FR-RN-2 | Before starting, the platform shows an estimated cost (minutes of TTS + STT + judge calls) and refuses if it exceeds the configured budget. | S | Run with estimate > budget returns HTTP 402-style error with the estimate. |
| FR-RN-3 | Run creation writes the run and a `run.requested` event in one transaction (outbox); the planner expands the matrix and emits one `call.requested` per item (keyed by run_item_id); simulator consumers execute them with a per-run concurrency cap (default 3). | M | No more than N calls of a run active at once; a run never exists without its event. |
| FR-RN-4 | Each simulated call: caller LLM produces utterance in persona language → Timbre TTS → noise/codec processor → WebSocket to agent; agent audio → caller-side VAD + Prisma STT → caller LLM next turn. | M | End-to-end call with mock agent produces ≥ 4 turns. |
| FR-RN-5 | Caller ends the call when goal is achieved, patience runs out, agent ends the call, max turns reached, or hard timeout (default 5 min). | M | Every call ends with a recorded `end_reason`. |
| FR-RN-6 | Interrupting personas start speaking 0.8–2.5 s into an agent turn (seeded random). | M | Barge-in attempts logged with timestamps. |
| FR-RN-7 | Record caller track, agent track (both mono, 16 kHz PCM) and a mixed stereo file. | M | Three files per call, durations within 100 ms of each other. |
| FR-RN-8 | Store per turn: speaker, caller ground-truth text (pre-TTS), caller-side STT of agent speech, start/end ms, and glass-box agent transcript if available. | M | Turns table populated. |
| FR-RN-9 | Infrastructure failures retry via `retry.30s` then `retry.5m` topics; after 3 attempts the event goes to the DLQ. Low scores never retry. Throttled items (run at its cap) re-queue without using an attempt. | M | Kafka integration tests: 3 failures → one DLQ row; throttling never reaches DLQ. |
| FR-RN-10 | Runs can be cancelled; in-flight calls hang up cleanly. | S | Cancel within 10 s. |
| FR-RN-11 | Text-only dry-run mode: skip TTS/STT and exchange text with glass-box agents, for cheap logic testing. | S | Dry run of 20 items costs zero Gnani credits. |

### 1.6 Evaluation (F8, F9, F16)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-EV-1 | Compute deterministic metrics per call: response latency p50/p90/p95, first-greeting latency, barge-in attempts/honoured, agent stop time after interruption, silence gaps > 2 s, turns count, talk ratio, repeated-utterance count. | M | Values stored in `call_metrics`. |
| FR-EV-2 | Deterministic checks: mandatory disclosure present (regex/fuzzy), forbidden phrase absent, expected tool calls present and ordered (glass-box), language match (agent replies in caller's language family). | M | Each check stored with pass/fail + evidence turn. |
| FR-EV-3 | Gemini judge scores the 7 rubric dimensions (0–4) with evidence turn indices and a short reason each, plus `critical_failure`, `needs_human_review`, and `failure_types`. | M | Output validates against the JSON schema; invalid output retried once, then marked `judge_error`. |
| FR-EV-4 | Overall score = weighted sum normalised to 0–100. Pass = score ≥ 80 and no critical failure and all must-pass deterministic checks pass. | M | Unit test on formula. |
| FR-EV-5 | Every evaluation stores rubric version, prompt hash, model ID, temperature, tokens, latency. | M | Fields non-null. |
| FR-EV-6 | Critical failure or failed mandatory disclosure ⇒ `needs_human_review = true` regardless of judge output. | M | Rule enforced in code, not prompt. |
| FR-EV-7 | Human reviewer can submit per-dimension scores and notes for an evaluation. | S | Stored in `human_reviews`. |
| FR-EV-8 | Calibration endpoint computes Cohen's kappa (pass/fail) and Spearman (overall) between judge and human labels for a rubric version. | S | Returns metrics + sample count. |
| FR-EV-9 | PII masking before any text is sent to the judge. | M | Test strings with phone/Aadhaar/PAN patterns are masked. |

### 1.7 Post-call audit (F10)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-AU-1 | Upload WAV/MP3 (≤ 10 MB in v1), choose agent and language(s). | M | File stored; call created with `source = upload`. |
| FR-AU-2 | Transcribe via Prisma batch STT with diarization (2 speakers) and denoise. | M | Turns with speaker labels stored. |
| FR-AU-3 | Identify which speaker is the agent (heuristic: who speaks first + LLM check on content). User can swap if wrong. | M | `speaker_role` assigned; swap re-runs evaluation. |
| FR-AU-4 | Same deterministic checks (where computable) and same judge rubric as simulations. Scenario-specific success criteria are replaced by agent-level goals. | M | Evaluation stored with same rubric version. |
| FR-AU-5 | One-click "promote to regression": creates a `promoted` scenario from the call (goal + failure description) and a regression test with baseline score. | S | Scenario and regression test linked to source call. |

### 1.8 Dialect gap report (F11)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-DI-1 | Create a dialect dataset; upload clips via CSV manifest (`file, reference_text, language, dialect_label, speaker_id, consent`). | M | Rows without consent=true rejected. |
| FR-DI-2 | Run each clip through Prisma under selected conditions (default: `clean_16k`, `pstn_8k_alaw`, `pstn_street_10db`). | M | One `asr_result` row per clip × condition. |
| FR-DI-3 | Metrics per result: normalised WER, CER, entity accuracy (numbers, amounts, names), LLM intent-preserved flag. | M | Stored per row. |
| FR-DI-4 | Report aggregates per dialect × condition with sample count and 95% bootstrap confidence intervals; shows top misrecognised words/entities. | M | HTML report and dashboard heatmap render. |
| FR-DI-5 | Optional comparator engine (e.g. open-source Whisper) evaluated on the same clips. | C | Second engine column appears in the report. |
| FR-DI-6 | Report suggests `bias_list` terms (frequently missed domain words). | S | List shown in report. |

### 1.9 Regression and comparison (F14, F15, F20)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-RG-1 | Regression test has status `blocking`, `scheduled` or `manual`, a failure type, and baseline score. | S | Stored. |
| FR-RG-2 | "Run regression suite" creates a run of all blocking tests against an agent. Suite fails if any test scores below baseline − tolerance (default 5) or has a critical failure. | S | Run summary shows suite pass/fail. |
| FR-RG-3 | Compare two runs: per scenario/persona cell, show score delta and newly failing cells. | S | Comparison view lists regressions first. |
| FR-RG-4 | CLI/GitHub Action can trigger a run and exit non-zero on suite failure. | C | Script returns exit code 1 on failure. |

### 1.10 Dashboard (F12)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-DB-1 | Next.js web app pages: Overview, Agents, Scenarios, Personas, Noise profiles, Runs, New run wizard, Run detail, Run compare, Call detail, Audits, Dialect, Regression, Integrations (+ delivery log), DLQ, Calibration, API keys. | M | All pages reachable from the sidebar; Playwright smoke test per page. |
| FR-DB-2 | Run detail: pass rate, critical failures, score distribution, latency p50/p95, matrix heatmap (scenario × persona coloured by score), **live progress via SSE**. | M | Renders for a 40-call run in < 3 s; a newly evaluated call appears within 2 s without reload. |
| FR-DB-5 | The browser never receives API keys; all calls go through the Next.js server-side proxy. | M | No key in any client bundle or network response (checked in QA). |
| FR-DB-6 | Typed API client generated from the OpenAPI spec. | M | CI fails if `schema.d.ts` is stale. |
| FR-DB-3 | Call detail: audio player (mixed), transcript with turn timestamps, highlighted evidence turns, per-dimension scores with reasons, deterministic checks, metrics, "promote to regression" button. | M | Clicking an evidence turn seeks the audio. |
| FR-DB-4 | Dialect page: heatmap dialect × condition, metric selector (WER/CER/entity), drill-down to worst clips. | M | Renders from stored results. |

### 1.11 Mock target agent (F13)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-MK-1 | Pipecat bot "EMI Reminder Bot": Prisma STT → Gemini → Timbre TTS, served over the platform WebSocket protocol, Kannada/Hindi/English. | M | Responds to the test-connection check. |
| FR-MK-2 | Supports glass-box mode (sends transcripts and tool calls). | M | Control messages received by platform. |
| FR-MK-3 | Has 5 switchable planted bugs: (1) skips the recording disclosure, (2) doesn't confirm amounts, (3) replies in English to Kannada callers, (4) ignores interruptions (VAD off), (5) promises a waiver it can't give. | M | Each bug toggled via env/config; run detects ≥ 4. |

### 1.12 Cost tracking (F17)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-CO-1 | Log every external API call: provider, operation, units (audio seconds, characters, tokens), estimated cost, linked call/run. | S | `api_usage` rows created. |
| FR-CO-2 | TTS cache keyed by hash(text, voice, model, speed, language) to avoid re-paying for identical lines. | S | Second identical request served from cache. |

### 1.13 Integrations (F22–F24, F29)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-IN-1 | Connectors implement a common interface (`10-integrations-and-dx.md §1.1`) and are discovered via the `pareeksha.connectors` entry point. | M | A connector in a separate pip package appears in `GET /integrations/connectors` without core changes. |
| FR-IN-2 | Integrations CRUD with per-connector config validation; secrets encrypted at rest and never returned by the API. | M | `GET /integrations/{id}` shows `secrets_set: true`, never the value; DB column is ciphertext. |
| FR-IN-3 | `POST /integrations/{id}/test` runs the connector's test and stores the result. | M | Bad HubSpot token → `ok: false` with reason. |
| FR-IN-4 | Sink delivery on `evaluation.completed` / `run.completed`, filtered by event type, agent, only-failed, score threshold. | M | Filtered-out events create `skipped` or no deliveries as configured. |
| FR-IN-5 | Outbound deliveries are idempotent per (integration, event). | M | Replaying the same event twice creates one HubSpot note / one webhook POST. |
| FR-IN-6 | Generic Webhook sink: HMAC-signed POST with timestamp; configurable events; no transcript by default. | M | Receiver test verifies signature; payload matches spec. |
| FR-IN-7 | Generic Webhook source: `POST /webhooks/inbound/{integration_id}` verifies signature and timestamp (5 min window), SSRF-checks the recording URL, dedupes by `external_id`, creates an import call and `audit.requested`. | M | Bad signature → 401; same external_id twice → one call; private-IP URL → 422. |
| FR-IN-8 | HubSpot sink: match contact by `crm_contact_id`, phone or email; create a note associated to the contact; no match → `skipped`. | M | Against mocked HubSpot API: note body contains score, pass/fail, failure types, link. |
| FR-IN-9 | Delivery log per integration with status, HTTP code, external id, response excerpt, and manual redeliver. | S | Visible on the Integrations page. |
| FR-IN-10 | DLQ viewer lists dead letters with error and lets the user replay or discard. | S | Replay re-publishes with `attempt=1`; status becomes `replayed`. |

### 1.14 Developer experience (F25–F28)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-DX-1 | `docker compose up` starts the full stack; `make demo` seeds data, creates an API key, registers the mock agent and runs a 10-call demo. | M | Fresh clone on a laptop shows an evaluated call in < 20 min. |
| FR-DX-2 | API keys with scopes (`read`, `runs:write`, `audits:write`, `admin`); stored hashed; shown once on creation. | M | Wrong scope → 403. |
| FR-DX-3 | `pareeksha-sdk` Python client (sync + async) covering agents, runs (create/wait), audits, regression, DLQ. | M | SDK example in README runs against the demo stack. |
| FR-DX-4 | CLI: `login`, `apply`, `run`, `regress`, `audit`, `dlq list/replay`, `doctor`; non-zero exit on failed threshold. | M | `pareeksha run --fail-under 101` exits 1. |
| FR-DX-5 | `pareeksha.yaml` config-as-code applied idempotently by name. | S | Applying twice changes nothing. |
| FR-DX-6 | GitHub Action runs a suite and writes a job summary; fails the check on regression. | S | Example workflow fails on a PR that enables a mock-agent bug. |
| FR-DX-7 | Agent adapters: `audio_v1` and Pipecat (with `PareekshaFrameSerializer`) with runnable examples. | M | Both examples pass a contract test. |
| FR-DX-8 | LiveKit adapter with example. | S | — |
| FR-DX-9 | Vapi adapter with example. | C | — |
| FR-DX-10 | Docs: quick start, connect Pipecat bot, connect any bot, webhook in, HubSpot out, GitHub Action, write a connector, operate Kafka. | M | Each guide followed once from a clean clone by QA. |

---

## 2. Non-functional requirements

| ID | Category | Requirement | Pri |
|---|---|---|---|
| NFR-1 | Performance | 20-call run with concurrency 4 finishes in < 15 min (calls ≤ 2 min each). | M |
| NFR-2 | Performance | Platform overhead added to measured agent latency ≤ 50 ms (measured by loopback test against an echo agent). | M |
| NFR-3 | Reliability | ≥ 95% of simulated calls finish without infrastructure error against the mock agent. | M |
| NFR-4 | Reliability | At-least-once delivery with idempotent consumers: duplicate delivery or a crash mid-handler causes no duplicate evaluation, call or CRM note (offsets committed only after the DB commit; `processed_events` + unique keys). | M |
| NFR-4b | Reliability | Kafka unavailable: the API keeps accepting requests; the outbox drains when Kafka returns, in order per key. | M |
| NFR-4c | Scalability | Each pipeline stage scales by adding consumer instances (≤ partitions, default 6) with no code change. | M |
| NFR-5 | Reproducibility | Given same seed, persona, scenario, noise profile and pinned models, caller's first utterance and noise are identical. LLM turns after that may vary; this is documented. | M |
| NFR-6 | Reproducibility | Judge runs at temperature 0 with a pinned model ID and versioned rubric. | M |
| NFR-7 | Auditability | Every score traceable to: rubric version, prompt hash, model ID, input transcript snapshot. | M |
| NFR-8 | Security | API keys only from environment/secret store; never logged; never sent to the browser. | M |
| NFR-9 | Privacy | PII masking before judge; synthetic fixtures only; consent flag required on dialect clips; retention setting for audio. | M |
| NFR-10 | Observability | Structured JSON logs with `run_id`, `call_id`, `job_id`; per-call event timeline stored. | M |
| NFR-11 | Portability | Runs locally with `docker compose up` (Kafka KRaft + Postgres + API + outbox relay + workers + web + mock agent); works with managed Kafka by config only. | M |
| NFR-15 | Security | Webhooks signed both ways (HMAC-SHA256 + timestamp); SSRF guard on fetched URLs; connector secrets encrypted; API keys hashed. | M |
| NFR-16 | Observability | Consumer lag per group, outbox backlog and open DLQ count visible at `/metrics/summary` and in the web app. | S |
| NFR-12 | Maintainability | All Gnani calls go through one client module; all LLM calls through one module; ≥ 70% unit-test coverage on `audio/` and `evaluation/`. | S |
| NFR-13 | Extensibility | Adding a language = new personas + normaliser config; no core code change. | S |
| NFR-14 | Usability | A new user can run the demo end to end from the README in < 20 min. | S |

---

## 3. Constraints and assumptions

- **C-1** Must use Gnani Prisma (STT) and Timbre (TTS) for speech. The judge and caller brain use the configured LLM (DeepSeek by default, Gemini optional); speech providers are pluggable (Gnani default).
- **C-2** Built by a multi-agent AI team under an orchestrator in 5 days (Sat 24 – Wed 28 Oct 2026), with Preetham as human owner; see `AGENTS.md`.
- **C-3** Python 3.11 (not 3.13: `audioop` was removed in 3.13; if you must use 3.13, install `audioop-lts`).
- **A-1** Agents under test can be reached over WebSocket using the platform's audio protocol (§ API spec) or Pipecat's serializer.
- **A-2** Gnani API behaviour matches docs; verified on Day 1.
- **A-3** Dialect clips (≥ 20 per dialect) can be collected from friends/family with consent.

## 4. Traceability

| PRD goal | Requirements |
|---|---|
| Goal 1: crash-test matrix | FR-AG-*, FR-SC-*, FR-PE-*, FR-NP-*, FR-RN-* |
| Goal 2: score every call | FR-EV-* |
| Goal 3: audit uploads | FR-AU-* |
| Goal 4: dialect report | FR-DI-* |
| Goal 5: regression | FR-RG-* |
| Goal 6: web app | FR-DB-*, FR-MK-* |
| Goal 7: Kafka backbone | FR-RN-3, FR-RN-9, NFR-4, NFR-4b, NFR-4c |
| Goal 8: adoption | FR-DX-* |
| Goal 9: integrations | FR-IN-* |
