# 09 — Build Plan · v0.2 (5 days, multi-agent)

The full task board, roles and rules live in **[`AGENTS.md`](AGENTS.md)** — that file is what the orchestrator runs. This page is the one-screen summary for Preetham.

**Window:** Sat 24 Oct → Wed 28 Oct 2026. The Gnani challenge deadline (10 Nov, if eligible) leaves ~12 days of buffer for polish, real-world testing and the launch post.

## Day by day

| Day | Theme | By end of day |
|---|---|---|
| **1 · Sat 24** | Contracts & foundations | Keys in; contracts frozen as code (events, connector interface, OpenAPI); Kafka + Postgres + API up in Compose; consumer framework with retry/DLQ tests; Gnani smoke tests; line simulator; designs done; Next.js scaffold |
| **2 · Sun 25** | Core engines | CRUD + seeds; run → planner → `call.requested`; mock EMI agent with 5 bugs; caller pipeline; Gemini client; metrics/checks; connector framework + webhook sink; first web pages |
| **3 · Mon 26** | Evaluation, audit, integrations | 12-call run completes through Kafka; judge + scoring; audits; HubSpot sink; webhook source; SSE live progress; run pages; ≥ 4/5 planted bugs caught |
| **4 · Tue 27** | Product complete | Dialect report; Pipecat adapter (+ LiveKit if time); SDK + CLI + GitHub Action; regression + calibration; call detail; all remaining pages; Playwright + contract tests |
| **5 · Wed 28** | Harden, demo, publish | 40-call acceptance run; P0/P1 fixes; 30 calls labelled; README + guides tested from a clean clone; demo video; v1.0.0 public |

## Your own tasks (Preetham)

| When | Task | Why it matters |
|---|---|---|
| Day 1 morning | **H-01:** Gnani + Gemini keys, confirm Timbre v3.0, pin Gemini model, generate `SECRET_KEY` | Everything on the critical path waits for this |
| Day 1 | Approve contracts (TL-01) and designs (DES-01) | Contracts are frozen after this |
| Day 1 | **Start collecting dialect clips** (WhatsApp friends/family a 10-sentence script + consent) | Needed by Day 4; slowest thing to get |
| Day 1 | Create a free HubSpot developer account + private app token | Needed for INT-02's live test on Day 3 |
| Day 3 | Watch a scored call and a HubSpot note appear | Sanity check before the big push |
| Day 4 | **H-02:** upload ≥ 20 clips per dialect group | Dialect report |
| Day 5 | Label 30 calls (EVAL-06), record the 60 s demo, approve the release | Calibration numbers + launch |

## Daily routine for the orchestrator
1. Morning: PJM posts the day's task list from `AGENTS.md §7` into `STATUS.md`; TL confirms no contract changes pending.
2. Midday: blockers > 2 h escalated to Preetham.
3. Evening: QA runs the full test suite; PJM writes the end-of-day report (done, blocked, critical path, credits used, consumer lag, DLQ count).

## If a day slips
PJM applies the cut list in `AGENTS.md §10`, top first. Never cut: mock agent with bugs, judge with evidence, Kafka outbox + idempotency + retry + DLQ, call detail page, dialect table, HubSpot sink, demo video.
