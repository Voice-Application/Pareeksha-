# 01 — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Product | Pareeksha (working name) |
| Owner | Preetham |
| Status | Draft v0.2 (Kafka, Next.js, built for adoption, CRM connectors) |
| Date | 23 Oct 2026 |
| Target v1 date | Wed 28 Oct 2026 (5-day multi-agent build, see `AGENTS.md`) |
| Outside deadline | Gnani challenge submission, 10 Nov 2026 (if eligible) |

---

## 1. Problem

Indian companies are putting voice AI agents on phone lines for collections, insurance renewals, onboarding and support. These agents break in ways that are specific to India:

- **Code-mixed speech.** Callers switch mid-sentence: *"Sir, naan EMI already pay maadiddini, but message banilla."* Many STT models miss the switch.
- **Narrowband, noisy phone lines.** Most calls arrive at 8 kHz over compressed codecs, from markets, buses and autos. Clean-audio demos hide this.
- **Dialect variation.** Mysuru, Hubballi-Dharwad and Mangaluru Kannada differ; so do Delhi and Bhojpuri-influenced Hindi. A single "Kannada WER" number hides which callers fail.
- **Domain vocabulary.** EMI, UPI, CIBIL, NEFT, policy numbers, amounts in lakhs — these get misheard and the agent then acts on the wrong value.
- **Behaviour.** Callers interrupt, go silent, get angry, ask to speak to a human. Prompt changes silently break flows that used to work.

Today, teams test by **manually calling their own bot** a few times. Global testing tools (Hamming, Cekura, Coval, Roark, Bluejay) exist, but they route Indian languages to third-party ASR, don't model Indian telephony as a named condition, and don't report gaps by dialect.

## 2. Vision

> *Before your voice agent talks to a real Indian customer, let a thousand synthetic ones break it first. After launch, audit every real call with the same judge, and send the results straight into the tools your team already uses.*

## 3. Target users

| Persona | Who | What they need |
|---|---|---|
| **Voice agent builder** (primary) | Prompt engineer / AI engineer building a voice bot for an Indian client | Find failures before the client does; prove a prompt change didn't break old flows |
| **QA / ops lead** | Person responsible for call quality after launch | Score real calls automatically instead of listening to 2% of them |
| **ASR / voice platform team** | Team choosing or tuning an STT model | See which dialects and line conditions fail, with numbers |
| **Platform / integration engineer** | Engineer at a company adopting Pareeksha | One-command setup, SDK/CLI, CI gate, connectors to their CRM and telephony |
| **Hiring manager / reviewer** (portfolio context) | Reviewer at a voice AI company | A clear demo that shows production understanding |

## 4. Goals and non-goals

### Goals (v1)
1. Run a **matrix of synthetic test calls** (persona × scenario × noise condition) against a voice agent over WebSocket, in Kannada, Hindi and code-mixed speech.
2. **Score every call** with deterministic checks plus a Gemini judge on a fixed, versioned rubric with evidence.
3. **Audit uploaded real call recordings** with the same rubric.
4. Produce a **dialect / line-condition ASR gap report** from real native-speaker clips.
5. **Promote failed calls into regression tests** and re-run them on demand.
6. A **Next.js web app** that makes all of this visible in a 60-second demo, with live run progress.
7. **Event-driven backbone on Kafka** so each stage scales and retries independently.
8. **Easy adoption by other teams:** one-command setup, Python SDK + CLI, GitHub Action, agent adapters (Pipecat first).
9. **Integrations:** a plugin connector framework; v1 ships a signed Generic Webhook (in and out) and a HubSpot sink.

### Non-goals (v1)
- Real PSTN/SIP calls (Exotel, Twilio, LiveKit SIP) — v2.
- Live streaming monitoring of production calls — v2.
- Multi-tenant SaaS: login, teams, billing — v2 (API keys exist in v1 for programmatic access).
- Building every CRM connector — v1 builds HubSpot + Generic Webhook; Salesforce, Zoho, LeadSquared, Freshdesk, Exotel and Slack are designed for, not built.
- High concurrency (more than ~5 simultaneous simulated calls).
- Languages beyond Kannada, Hindi, Indian English and their code-mixes (the design keeps this extensible).
- Fine-tuning any model.

## 5. User stories

### Crash testing
- **US-1** As a builder, I register my agent (name, WebSocket URL, language, description of what it should do, mandatory disclosures) so the platform knows how to call it and what "correct" looks like.
- **US-2** As a builder, I write a scenario in plain language ("caller says they already paid the EMI; agent must ask for the UTR number and not threaten") or let the platform generate scenarios from my agent's prompt.
- **US-3** As a builder, I pick personas (e.g. *frustrated Kanglish auto driver*, *slow elderly Hindi speaker*, *interrupter*) and noise profiles (*clean*, *8 kHz phone*, *market at 5 dB*) and launch a run.
- **US-4** As a builder, I see each call's transcript, audio, latency numbers, judge scores per dimension, and the exact turns that caused a failure.
- **US-5** As a builder, I compare two runs (before/after a prompt change) and see which scenarios regressed.

### Audit
- **US-6** As a QA lead, I upload a recorded call (WAV/MP3) and receive a transcript with speakers separated, a rubric score, compliance check results and flagged issues.
- **US-7** As a QA lead, I mark a judge score as wrong and give my own score, so the judge can be calibrated over time.
- **US-8** As a QA lead, I turn a failed real call into a regression scenario with one click.

### Dialect report
- **US-9** As an ASR team member, I upload a set of native-speaker clips tagged by dialect with reference transcripts.
- **US-10** I run them through Prisma under clean, 8 kHz phone and noisy conditions and see normalised WER, CER and entity accuracy per dialect × condition, with the worst-hit words and entities listed.

### Adoption & integrations
- **US-11** As a platform engineer, I run `docker compose up` and `make demo` and see an evaluated call within 20 minutes.
- **US-12** As a builder, I add a serializer to my Pipecat bot (or a tiny WebSocket endpoint to any bot) and Pareeksha can call it.
- **US-13** As a builder, I keep scenarios in `pareeksha.yaml` in my repo, and a GitHub Action blocks my PR if the regression suite fails.
- **US-14** As a QA lead, our telephony system posts each finished call's recording URL to a signed webhook, and Pareeksha audits it automatically.
- **US-15** As a QA lead, each audit result appears as a note on the customer's HubSpot contact (score, issues, link), without the transcript.
- **US-16** As an engineer, I can write a new connector (e.g. Zoho) as one module in my own pip package, without forking Pareeksha.
- **US-17** As an operator, I see failed events in a dead-letter view and replay them after fixing the cause.

## 6. Core concepts (glossary)

| Term | Meaning |
|---|---|
| **Agent (under test)** | The voice bot being tested. Reached over WebSocket in v1. |
| **Scenario** | What the caller wants and what success means. Language-independent. |
| **Persona** | Who the caller is: language, dialect label, voice, speed, emotion, patience, interruption habit. |
| **Noise profile** | Line and background condition: sample rate, codec, bandpass, background noise type, SNR. |
| **Run** | One launch of a test matrix. Contains many run items. |
| **Run item** | One (scenario, persona, noise profile) cell of the matrix → produces one call. |
| **Call** | One recorded conversation, simulated or uploaded. |
| **Evaluation** | The judge's scored output for a call, tied to rubric version and model ID. |
| **Regression test** | A scenario promoted from a failed call, with a baseline score that future runs must meet. |
| **Dialect dataset** | Real clips + reference transcripts, tagged by dialect, for the ASR gap report. |

## 7. Feature list and priority

| ID | Feature | Priority |
|---|---|---|
| F1 | Agent registry | Must |
| F2 | Scenario library (manual + LLM-generated from agent prompt) | Must |
| F3 | Persona library with 20 seed personas | Must |
| F4 | Noise profile library (8 named profiles) | Must |
| F5 | Simulated caller engine (Pipecat + Timbre + noise + caller-side Prisma STT) | Must |
| F6 | Run orchestration on Kafka (matrix expansion, consumer groups, retry topics, DLQ, concurrency cap) | Must |
| F7 | Call recording (separate caller/agent tracks + mixed) | Must |
| F8 | Deterministic metrics (latency, barge-in, silence, disclosures, loops) | Must |
| F9 | Gemini judge with versioned rubric, structured JSON, evidence | Must |
| F10 | Post-call audit of uploaded recordings | Must |
| F11 | Dialect ASR gap report | Must |
| F12 | Next.js web app (runs, live progress, call drill-down, dialect heatmap, integrations, DLQ) | Must |
| F13 | Mock target agent (EMI reminder bot with planted bugs) | Must (needed for demo) |
| F14 | Regression promotion + re-run | Should |
| F15 | Run-vs-run comparison | Should |
| F16 | Human review + judge calibration (Cohen's kappa) | Should |
| F17 | Credit/cost tracking and budget guard | Should |
| F18 | Glass-box mode (agent streams its own transcripts → measures *agent's* ASR accuracy against caller ground truth) | Should |
| F19 | Exportable HTML report per run | Could |
| F20 | GitHub Action (regression gate on PRs) | Should |
| F21 | PSTN/SIP calling, live monitoring, multi-tenant auth | Won't (v1) |
| F22 | Connector framework (entry-point plugins, encrypted secrets, delivery log) | Must |
| F23 | Generic Webhook connector (signed source + sink) | Must |
| F24 | HubSpot sink connector | Must |
| F25 | Python SDK + CLI (`pareeksha run/audit/regress/apply/dlq`) | Must |
| F26 | Agent adapters: `pareeksha-audio-v1` + Pipecat (Must), LiveKit (Should), Vapi (Could) | Must/Should/Could |
| F27 | Config-as-code `pareeksha.yaml` | Should |
| F28 | API keys with scopes | Must |
| F29 | Dead-letter viewer + replay | Should |
| F30 | Salesforce, Zoho, LeadSquared, Freshdesk, Exotel, Slack connectors | Won't (v1, designed for) |

## 8. Success metrics

### Product (does it work?)
| Metric | Target |
|---|---|
| A 20-call run (concurrency 4) completes end-to-end | < 15 min |
| Simulated calls that complete without infrastructure error | ≥ 95% |
| Judge agreement with your own manual labels on 30 calls (Cohen's kappa, pass/fail) | ≥ 0.6 for v1, ≥ 0.7 target |
| Planted bugs in the mock agent detected by the run | ≥ 4 of 5 |
| Dialect report covers | ≥ 3 Kannada dialect groups + Hindi + code-mixed, ≥ 20 clips each |
| Duplicate Kafka delivery or worker crash causes a duplicate evaluation or CRM note | 0 times in tests |
| Clean clone → first evaluated call | < 20 min |
| Webhook-imported call → HubSpot note | < 3 min |

### Portfolio (does it land?)
- 60-second demo video showing: launch run → watch failure → drill into the exact turn → promote to regression → fix prompt → re-run passes.
- README with architecture diagram, one real dialect heatmap, and honest limitations.
- LinkedIn/X post with the demo.

## 9. Demo storyline (design target)

1. Register **"EMI Reminder Bot"** (mock agent, Kannada + Hindi).
2. Launch a run: 5 scenarios × 4 personas × 2 noise profiles = 40 calls.
3. Dashboard shows 72% pass. Click a failure: *frustrated Kanglish caller on a market-noise 8 kHz line said "naal-ku saavira" (4,000); agent heard 40,000 and confirmed the wrong amount.* Critical failure, evidence turn highlighted, audio plays.
4. Promote to regression. Add `bias_list` / confirm-amount instruction to the bot prompt. Re-run: passes.
5. Switch to Dialect tab: heatmap shows North Karnataka Kannada on 8 kHz + noise has the worst entity accuracy.
6. Upload a real recorded call → audit score and missing-disclosure flag.
7. Show the HubSpot contact: the audit note appeared automatically.
8. Show a PR in the bot's repo: the GitHub Action check failed on a prompt change, then passed after the fix.

## 10. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Gnani API differs from research notes | Days lost | Day-1 smoke tests; thin client wrapper so changes stay in one file |
| Credit budget (5,000 programme credits, if applicable) runs out | Can't run demos | Budget guard; text-only "dry run" mode for logic tests; cache TTS audio per (text, voice, speed) |
| Synthetic voices too clean / not dialect-real | Results look fake | Noise + codec pipeline; dialect claims only from real clips |
| LLM judge inconsistent | Untrustworthy scores | Temperature 0, pinned model, structured output, deterministic checks for hard facts, calibration set |
| Turn-taking between two bots deadlocks (both wait / both talk) | Calls hang | Caller-side VAD, max-silence nudges, hard call timeout |
| Scope creep | Nothing finished | Strict Must list; v2 parking lot in this doc; cut list in AGENTS.md |
| Kafka adds operational complexity | Lost or stuck work | Outbox, idempotent consumers, retry topics + DLQ, consumer-lag on `/metrics/summary`; tested failure cases |
| 5-day agent build produces inconsistent pieces | Integration hell on Day 4–5 | Contracts frozen by the Tech Lead on Day 1 (events, connector interface, OpenAPI); QA veto on merges |
| CRM API details differ from notes | HubSpot sink slips | Build against a mock first; verify with a free developer account on Day 3 |
| Collecting dialect recordings | Report empty | Start collecting on Day 2 from friends/family with consent; 20 clips per dialect is enough |

## 11. Privacy and ethics

- Fixtures, scenarios and demo calls use **synthetic** names, numbers and IDs only.
- Uploaded recordings: shown a consent reminder; PII patterns (10-digit phone numbers, 12-digit Aadhaar-like numbers, PAN-like `AAAAA9999A`) are masked in transcripts before being sent to the judge.
- Dialect clips: collected with speaker consent, stored with a speaker ID, not a name.
- Configurable retention: audio files can be auto-deleted after N days.

## 12. v2 parking lot

- PSTN/SIP calling via Exotel or LiveKit SIP for true phone-path tests and DTMF.
- Live streaming monitoring of production calls with alerts.
- More languages (Tamil, Telugu, Marathi, Bengali).
- Real auth (SSO), multi-tenant workspaces.
- More connectors: Salesforce, Zoho CRM, LeadSquared, Freshdesk, Exotel source, Slack alerts.
- Schema registry for event contracts.
- Public Indic voice-agent leaderboard.
- Shadow-mode replay of production audio against a new agent version.
