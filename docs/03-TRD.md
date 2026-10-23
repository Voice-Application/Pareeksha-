# 03 — Technical Requirements Document (TRD) · v0.2

This document explains **how** each part is built. Diagrams: `04-system-design.md`. Tables: `05-database-design.md`. Connectors, SDK, CLI and adapters: `10-integrations-and-dx.md`.

**What changed from v0.1:** Kafka replaces the Postgres job queue (§10), Next.js replaces Streamlit (§11), and the platform is built for other teams to adopt, with a CRM connector framework (§12).

> ✅ Gnani endpoints, auth header, model names, voices and language codes were **checked against the published `gnani-vachana` 0.8.2 and `pipecat-gnani` 0.5.12 packages** (23 Oct 2026). Package versions in this doc were checked against PyPI/npm the same day. Behaviour (latency, accuracy, optional headers, credit cost) is still unverified until the API is called on Day 1.

---

## 1. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend language | Python 3.11 / 3.12 | Pipecat, Gnani SDK, audio libs; `audioop` built in (3.13 needs `audioop-lts`) |
| API | FastAPI + Uvicorn | Async, OpenAPI spec is the contract for the web app and SDK |
| Data models | Pydantic v2 | API schemas, event schemas, LLM structured output |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic, `psycopg` 3 | — |
| System of record | PostgreSQL 16 | Agents, runs, calls, scores, integrations |
| **Event backbone** | **Apache Kafka (KRaft mode, no ZooKeeper)** | Durable event log between pipeline stages; scale by adding consumers; replay; fits v2 live-call streaming |
| Kafka client | **aiokafka** ≥ 0.14 | asyncio-native, matches the rest of the backend |
| Real-time audio | Pipecat ≥ 1.13 + **`pipecat-gnani`** | Gnani STT/TTS services, VAD, WebSocket transports |
| Gnani SDK | `gnani-vachana` ≥ 0.8.2 | REST/stream/batch STT, TTS outside Pipecat |
| STT | Gnani Prisma (stream for live calls; batch for audits; REST for dialect clips) | India-trained, 8 kHz-aware |
| TTS | Gnani Timbre **v3.0** (13 voices, every voice speaks all 10 languages) | v2.5 has only 2 Kannada voices |
| LLM | Gemini via `google-genai`, pinned model ID | Caller brain, judge, scenario generation |
| Audio DSP | numpy, scipy.signal, soundfile, `audioop` | Exact SNR, bandpass, A-law round trip |
| Text metrics | jiwer, indic-nlp-library, rapidfuzz | WER/CER, Indic normalisation, fuzzy checks |
| **Web app** | **Next.js 16 (App Router) + React 19 + TypeScript + Tailwind 4 + shadcn/ui** | Production-grade UI, portfolio quality |
| Web data | TanStack Query 5, `openapi-typescript` 7 + `openapi-fetch` (generated, typed client) | API types never drift from the backend |
| Web media/charts | wavesurfer.js 8 (waveform + regions), Recharts 3 | Evidence-turn seeking, heatmaps, latency charts |
| Live updates | Server-Sent Events from FastAPI | One-way progress stream; simpler than WebSockets |
| SDK / CLI | `pareeksha-sdk` (httpx) + Typer CLI | Others adopt it from their own code and CI |
| Secrets at rest | `cryptography` Fernet with `SECRET_KEY` | Encrypt connector tokens |
| Logging | structlog JSON | Correlation IDs |
| Tests | pytest, pytest-asyncio, respx, Playwright | Unit, contract, e2e |
| Packaging | Docker Compose | `docker compose up` = whole stack |

---

## 2. Processes

| Process | Command | Consumer group | Responsibility |
|---|---|---|---|
| `api` | `uvicorn pareeksha.api.main:app` | — (producer via outbox; SSE reader) | REST, uploads, webhooks in, writes rows + outbox events |
| `outbox-relay` | `python -m pareeksha.workers.outbox_relay` | — | Publishes unpublished `outbox_events` rows to Kafka |
| `planner` | `python -m pareeksha.workers.planner` | `planner` | `run.requested` → expand matrix → `call.requested` × N |
| `simulator` | `python -m pareeksha.workers.simulator` | `simulator` | Runs a simulated call (Pipecat) → `call.completed` |
| `auditor` | `python -m pareeksha.workers.auditor` | `auditor` | Uploaded/imported recording → batch STT → turns → `call.completed` |
| `evaluator` | `python -m pareeksha.workers.evaluator` | `evaluator` | Metrics + checks + judge + scoring → `evaluation.completed` |
| `finalizer` | `python -m pareeksha.workers.finalizer` | `finalizer` | Updates run summary; when all items done → `run.completed` |
| `integrations` | `python -m pareeksha.workers.integrations` | `integrations` | Fans events out to sink connectors (HubSpot, webhook) |
| `dialect` | `python -m pareeksha.workers.dialect` | `dialect` | Clip × condition ASR eval; aggregate when dataset done |
| `generator` | `python -m pareeksha.workers.generator` | `generator` | LLM scenario generation |
| `retrier` | `python -m pareeksha.workers.retrier` | `retrier` | Moves due messages from retry topics back to their target topic |
| `dlq-recorder` | `python -m pareeksha.workers.dlq_recorder` | `dlq-recorder` | Copies DLQ messages into `dead_letters` for the UI/replay |
| `web` | `next start` (in `web/`) | — | Dashboard; talks only to the API via its own server-side proxy |
| `mock-agent` | `python -m mock_agent.server` | — | Demo target bot |
| `kafka`, `postgres` | images | — | Infrastructure |

All Python workers share one image and one entry point framework (`pareeksha.events.consumer.run_consumer`), so a new stage is one handler function plus one line in Compose.

---

## 3. Gnani integration (`pareeksha/gnani/`)

Inside Pipecat pipelines use **`pipecat-gnani`** (Pipecat has no `[gnani]` extra):
`from pipecat_gnani.stt import GnaniSTTService` (WS streaming) / `GnaniHttpSTTService` (segmented REST);
`from pipecat_gnani.tts import GnaniTTSService` (WS, interruptible) / `GnaniHttpTTSService` / `GnaniSSETTSService`.

Elsewhere (audit, dialect, persona previews) wrap **`gnani-vachana`**: `GnaniSTTClient` (REST), `GnaniSTTStreamClient` (WS), batch client (`gnani.stt.batch_async`), `GnaniTTSClient` / `GnaniTTSStreamClient`.

Confirmed from SDK source:
- Base `https://api.vachana.ai`; header `X-API-Key-ID`; STT `/stt/v3`, `/stt/v3/stream`; TTS `/api/v1/tts`, `/api/v1/tts/inference`, `/api/v1/tts/sse`.
- Languages: `bn-IN en-IN gu-IN hi-IN kn-IN ml-IN mr-IN pa-IN ta-IN te-IN`; TTS also accepts `auto`. **No separate Hinglish/Kanglish code** — send code-mixed text with the base language or `auto`; compare on Day 1.
- TTS models `timbre-v2.0`, `timbre-v2.5` (SDK default), `timbre-v3.0`. Encodings `linear_pcm`, `oggopus`, `pcm_mulaw`, `pcm_alaw`; sample rates 8000–48000.
- v2.5 Kannada voices: Saanvi, Kavin. v3.0 voices (all languages): Avinash, Shivani, Lakshmi, Kalpana, Shubham, Prakash, Devansh, Yashraj, Chetana, Vasudha, Riyaa, Tarika, Harshad.

Still unverified: telephony tuning headers (`x-vad-threshold`, `x-min-silence-ms`), batch diarization/denoise option names, credit cost.

Rules: every call logs `api_usage`; 3 retries with backoff on 5xx/timeouts only; TTS disk cache keyed by sha256(model|voice|language|speed|rate|encoding|text); batch results downloaded immediately (URLs expire).

## 4. LLM module (`pareeksha/llm/`)

`GeminiClient.generate_json(prompt, schema, *, temperature, model_id)` with structured output, one repair retry on validation failure, usage logging. Versioned Jinja2 prompts in `pareeksha/llm/prompts/` (`caller_v1.j2`, `judge_v1.j2`, `scenario_gen_v1.j2`, `role_detect_v1.j2`, `asr_intent_v1.j2`); `prompt_hash` = sha256 of the unrendered template.

| Use | Temperature |
|---|---|
| Judge, role detection, ASR intent | 0 |
| Caller brain | 0.7 |
| Scenario generation | 0.8 |

---

## 5. Simulation engine (`pareeksha/simulation/`)

Unchanged in design from v0.1; it now runs inside the `simulator` consumer.

```
agent ──► transport.input ─► CallTap(in) ─► SileroVAD ─► GnaniSTTService ─► TurnTracker
  ▲                                                                            │
  │           CallerBrain (Gemini: persona + scenario + history) ◄─────────────┘
  │                  │ utterance text (= ground truth)
  │                  ▼
  └── transport.output ◄─ CallTap(out) ◄─ LineSimulator ◄─ GnaniTTSService(persona voice/speed)
                         AudioRecorder taps both directions
```

| Processor | Job |
|---|---|
| `CallTap` | Monotonic timestamps on every frame → recorder + event log |
| `LineSimulator` | Noise profile on outgoing audio (resample → bandpass → SNR noise → codec → loss → resample back) |
| `TurnTracker` | VAD + transcripts → turns; detects end of agent turn |
| `CallerBrain` | Gemini → `{utterance, end_call, goal_status, notes}` |
| `BargeInScheduler` | Interrupts at seeded 0.8–2.5 s into an agent turn (p = 0, .25, .5, .8 by level) |
| `GlassBoxListener` | Agent's transcript / tool_call / call_end messages |

Transports: the agent is reached through an **adapter** (`pareeksha/adapters/`): `audio_v1` (native protocol), `pipecat` (Pipecat serializer), `livekit` (join a room as a participant), `vapi` (Vapi WebSocket transport). See `10-integrations-and-dx.md §4`.

Turn-taking valves: agent speaks first by default; caller says "Hello?" after 6 s of silence; one nudge after 8 s mid-call silence, then `agent_silent`; hard timeout 300 s; max turns from scenario; audio sent at real-time pace.

Latency = agent VAD speech start − caller last frame sent (single monotonic clock, includes network; platform overhead measured against an echo agent, target ≤ 50 ms). Barge-in honoured = agent silent ≥ 300 ms within 1500 ms of caller starting. Recording: caller (degraded) + agent tracks at 16 kHz mono + aligned stereo mix.

## 6. Line simulator (`pareeksha/audio/`)

Per 20 ms chunk at 16 kHz: float32 → resample to profile rate → 300–3400 Hz Butterworth bandpass (stateful) → background noise at SNR measured on **speech-active** samples (`noise × sqrt(Ps / (Pn · 10^(SNR/10)))`, verified exact in a quick test) → optional clipping → **G.711 A-law** round trip (Indian PSTN; µ-law optional) → optional packet loss (drop 20 ms frames) → resample back to 16 kHz. Seeded RNG; chunked output == whole-file output. Noise clips in `data/noise/<category>/` with licences recorded.

## 7. Evaluation engine (`pareeksha/evaluation/`)

Runs in the `evaluator` consumer for every `call.completed`:
1. Snapshot (masked turns, metrics, tool trace, goals) → 2. deterministic metrics → 3. deterministic checks (disclosure, forbidden, language match, tool calls, loops, amount read-back) → 4. Gemini judge (rubric in `08`) → 5. scoring **in code** + forced review rules → 6. save evaluation + `processed_events` row in one transaction → 7. produce `evaluation.completed`.

PII masking before the judge: Indian mobile, Aadhaar-like, PAN-like, email, card-like numbers. `calls.metadata` (customer phone/email for CRM matching) is **never** included in judge input.

## 8. Post-call audit (`pareeksha/audit/`)

Triggered by `audit.requested` (from `POST /audits`, the inbound webhook connector, or future source connectors). Download/convert → Gnani batch STT (2-speaker diarization, denoise, agent `bias_list`) → role detection (first speaker + LLM check) → turns → `call.completed`. Imported calls are deduplicated by `external_refs (integration_id, external_id)`.

## 9. Dialect pipeline (`pareeksha/dialect/`)

`POST /dialect-datasets/{id}/evaluate` writes one `dialect.clip.requested` per clip × condition (key = sample_id, so clips spread across partitions). The `dialect` consumer degrades the clip offline with the same `LineSimulator`, transcribes with Prisma REST, normalises (NFC, indic-nlp, numerals incl. lakh/crore, loanword script unification), computes WER/CER/entity accuracy/intent. When the count of `asr_results` reaches the expected total, it aggregates (speaker-grouped bootstrap CIs, top substitutions, `bias_list` suggestions) and writes `dialect_reports`.

---

## 10. Event backbone — Kafka

### 10.1 Cluster
- Local: single-broker KRaft (`apache/kafka` image), replication factor 1, `auto.create.topics.enable=false`; a one-shot `kafka-init` container creates topics.
- Production-ready path: 3 brokers, RF 3, `min.insync.replicas=2`, managed Kafka (Confluent Cloud, Aiven, MSK) — config only, no code change.

### 10.2 Topics (frozen contract; versioned names)

| Topic | Key | Producer(s) | Consumer group(s) | Partitions |
|---|---|---|---|---|
| `pareeksha.run.requested.v1` | run_id | api (outbox) | planner | 6 |
| `pareeksha.call.requested.v1` | **run_item_id** | planner, api (regression re-runs) | simulator | 6 |
| `pareeksha.audit.requested.v1` | call_id | api (outbox), source connectors | auditor | 6 |
| `pareeksha.call.completed.v1` | call_id | simulator, auditor | evaluator | 6 |
| `pareeksha.evaluation.completed.v1` | call_id | evaluator | finalizer, integrations | 6 |
| `pareeksha.run.completed.v1` | run_id | finalizer | integrations | 3 |
| `pareeksha.progress.v1` | run_id or call_id | all workers | api SSE (unique group per API instance, `auto.offset.reset=latest`) | 3 |
| `pareeksha.scenario.generate.requested.v1` | agent_id | api (outbox) | generator | 3 |
| `pareeksha.dialect.clip.requested.v1` | sample_id | api (outbox) | dialect | 6 |
| `pareeksha.retry.30s.v1` | original key | any consumer | retrier | 3 |
| `pareeksha.retry.5m.v1` | original key | any consumer | retrier | 3 |
| `pareeksha.dlq.v1` | original key | any consumer | dlq-recorder | 3 |

> **Why `call.requested` is keyed by run_item_id, not run_id:** keying by run_id would put a whole run on one partition, so only one simulator could process it at a time. Keying by item spreads a run across partitions; the per-run concurrency cap is enforced separately (§10.6).

Retention 7 days (progress topic: 1 day). Partition count is the ceiling on parallel consumers per group — 6 is plenty for v1 and can be raised later (only the key→partition mapping changes, which no consumer relies on for ordering across items).

### 10.3 Envelope (every message, JSON, UTF-8)

```json
{
  "event_id": "uuid",
  "type": "call.completed",
  "version": 1,
  "occurred_at": "2026-10-26T10:15:00Z",
  "correlation_id": "run_id or call_id",
  "causation_id": "event_id that caused this one",
  "attempt": 1,
  "producer": "simulator@host-3",
  "payload": { }
}
```
Payloads are Pydantic models in `pareeksha/events/schemas.py` — IDs and small facts only; large data (transcripts, audio) stays in Postgres/blob storage. Kafka headers carry `x-target-topic`, `x-not-before`, `x-error` on retry/DLQ copies. No schema registry in v1; the Pydantic models + `version` field are the contract (Avro/Protobuf + registry is a v2 option).

### 10.4 Producing — transactional outbox
The API never publishes directly. In the same DB transaction that creates a run (or audit, dataset job), it inserts the event into `outbox_events`. The `outbox-relay` claims unpublished rows (`FOR UPDATE SKIP LOCKED LIMIT 100`), publishes with `acks=all` and idempotent producer settings, then sets `published_at`. Result: a run can never exist without its event, or vice versa. If Kafka is down, the API keeps working and the outbox drains when Kafka is back.

Workers produce their *output* events after committing their DB transaction. If a worker crashes between commit and produce, the input message is redelivered, the `processed_events` check finds it already done, and the worker **re-produces the output event** before committing the offset (output events are idempotent for downstream consumers by `event_id`, which is derived deterministically: `uuid5(input_event_id, output_type)`).

### 10.5 Consuming — the consumer framework (`pareeksha/events/consumer.py`)

```python
@consumer(group="evaluator", topic=Topics.CALL_COMPLETED)
async def handle(env: Envelope[CallCompleted], ctx: Ctx) -> list[Outgoing]:
    ...  # do work inside ctx.tx (DB transaction); return events to produce
```
The framework:
1. Polls with `enable_auto_commit=False`; processes **one message at a time per consumer instance** (parallelism = instances ≤ partitions).
2. Opens a DB transaction; inserts `(group, event_id)` into `processed_events` — on conflict: already done → re-produce deterministic outputs, commit offset, move on.
3. Runs the handler inside the transaction; commits; produces returned events; **then commits the Kafka offset**.
4. On exception: classify. *Retryable* (timeouts, 5xx, connection errors) → produce a copy to `retry.30s` (attempt 2) or `retry.5m` (attempt 3) with `x-target-topic` and `x-not-before`; *permanent* (validation error, 4xx, attempt > 3) → produce to `dlq.v1` with `x-error`. Then commit the offset so the partition isn't blocked.
5. Long jobs: simulator sets `max_poll_interval_ms=900000` (15 min); calls are capped at 5 min.
6. Graceful shutdown on SIGTERM: stop polling, finish the current message, commit, leave group.

**Retrier:** consumes both retry topics; for each message, waits until `x-not-before` (pausing the partition; messages in one delay topic are already in due-time order), produces to `x-target-topic`, commits.

**DLQ:** `dlq-recorder` copies messages into `dead_letters`. `POST /dlq/{id}/replay` (or `pareeksha dlq replay`) re-publishes the original envelope with `attempt=1` to its original topic via the outbox.

### 10.6 Back-pressure and concurrency
- Global: number of `simulator` instances (Compose `deploy.replicas`, default 3).
- Per run: before starting a call, `UPDATE test_runs SET active_calls = active_calls + 1 WHERE id = :run AND active_calls < (config->>'max_concurrency')::int RETURNING id`. No row → the run is at its cap: send the message to `retry.30s` **without** incrementing `attempt` (header `x-reason: throttled`). Decrement in the same transaction that saves the finished call. A reconciler in `finalizer` recomputes `active_calls` from `run_items` every minute to heal crashes.
- Per agent rate limit: v2.

### 10.7 Delivery guarantees (what to tell a reviewer)
At-least-once delivery + idempotent consumers (`processed_events`, unique constraints, upserts) = effectively-once side effects in Postgres. External side effects (HubSpot, webhooks) are guarded by `integration_deliveries UNIQUE (integration_id, event_id, direction)`. Kafka transactions/EOS are deliberately not used: they don't cover Postgres or HTTP side effects anyway.

---

## 11. Web app (`web/`)

- **Next.js 16 App Router**, TypeScript strict, Tailwind 4, shadcn/ui components, lucide icons.
- **Server-side proxy (BFF):** browser calls `web/app/api/proxy/[...path]/route.ts`, which forwards to FastAPI with the API key from server env. The key never reaches the browser (NFR-8). SSE is streamed through the same proxy.
- **Typed client:** `pnpm gen:api` runs `openapi-typescript http://api:8000/openapi.json -o lib/api/schema.d.ts`; `openapi-fetch` + TanStack Query hooks wrap it. CI fails if the generated file is stale.
- **Live progress:** `GET /api/v1/runs/{id}/events` (SSE) — events `item.status`, `call.evaluated`, `run.completed`; the run page patches TanStack Query cache on each event; falls back to 5 s polling if SSE drops.
- **Call detail:** wavesurfer.js with two regions plugins (caller/agent), transcript list synced to playback, clicking an evidence turn seeks audio, judge dimensions with reasons, deterministic checks, promote-to-regression dialog.
- **Charts:** Recharts heatmaps (scenario × persona, dialect × condition), latency histograms.
- **Auth (v1):** single local user; optional `WEB_PASSWORD` basic gate via middleware. Real auth (NextAuth / Clerk) is v2.
- Pages and wireframe requirements: `02-requirements.md §1.10` and the designer's spec (AGENTS.md task DES-01).

## 12. Integrations & developer experience

Summary here; full spec in `10-integrations-and-dx.md`.
- **Connector framework** (`pareeksha/integrations/`): one module per connector implementing `Connector` (`name`, `direction`, `config_schema`, `test()`, `handle(event)` for sinks, `ingest(request)` for sources). Registered through the Python entry-point group `pareeksha.connectors`, so a third party can `pip install pareeksha-connector-zoho` without touching core code. Secrets Fernet-encrypted.
- **v1 connectors:** Generic Webhook (source + sink, HMAC-signed), HubSpot (sink: note on the matched contact with score, pass/fail, failure types, summary and link).
- **SDK + CLI:** `pip install pareeksha-sdk` → `Pareeksha(api_key).runs.create(...)`, CLI `pareeksha run|audit|regress|apply|dlq`.
- **Config-as-code:** `pareeksha.yaml` in the user's repo (agent, scenarios, personas, profiles) → `pareeksha apply`.
- **GitHub Action:** runs the regression suite on PRs that touch prompts; fails below threshold.
- **Agent adapters:** native protocol, Pipecat (Must), LiveKit (Should), Vapi (Could).
- **API keys** with scopes for all programmatic access.

---

## 13. Configuration

`pydantic-settings`; see `.env.example`. New in v0.2: `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_CLIENT_ID`, `KAFKA_SECURITY_PROTOCOL` (+ SASL vars for managed Kafka), `TOPIC_PARTITIONS`, `SECRET_KEY` (Fernet), `PUBLIC_BASE_URL` (links in CRM notes), `WEB_PASSWORD`, `PAREEKSHA_API_KEY` (web server → API).

## 14. Error handling

| Failure | Behaviour |
|---|---|
| Agent unreachable | Retryable → retry.30s → retry.5m → DLQ; run item `error` after attempt 3 |
| Agent hangs up mid-call | Not an error; call saved, `end_reason=agent_hangup`, evaluated |
| Gnani/Gemini 5xx / timeout | Client retries ×3, then retryable error → retry topics |
| Gnani/Gemini 4xx, invalid judge JSON after repair | Permanent → DLQ (evaluation stored as `judge_error`) |
| Kafka down | API keeps accepting (outbox buffers); workers reconnect with backoff |
| Postgres down | Consumers stop committing offsets; messages are redelivered when it returns |
| Worker crash | Group rebalance → message redelivered → idempotency check |
| HubSpot rate limit (429) | Retryable with `Retry-After` honoured |
| Budget exceeded mid-run | Remaining items `skipped_budget`; run `partial` |

## 15. Observability

structlog JSON with `event_id`, `correlation_id`, `run_id`, `call_id`, consumer group. Per-call `event_log`. `/health` checks DB + Kafka metadata. `/metrics/summary`: consumer lag per group (via admin client), outbox backlog, DLQ open count, credits used. Optional `kafka-ui` (kafbat) container behind the `tools` Compose profile.

## 16. Security & privacy

Secrets in env; connector secrets Fernet-encrypted; API keys stored as sha256 hashes with scopes; outbound webhooks HMAC-signed with timestamp (replay window 5 min); inbound webhooks verified the same way; SSRF guard on recording URLs (https only, block private IP ranges); uploads MIME-sniffed and size-limited; PII masked before the judge; CRM pushes contain no transcript by default; synthetic fixtures only.

## 17. Testing strategy

| Level | What |
|---|---|
| Unit | DSP (SNR, bandpass, codec, determinism), text normalisation, numerals, WER, PII, scoring, kappa, HMAC sign/verify, connector config validation |
| Contract | Gnani clients vs recorded fixtures; OpenAPI snapshot; event schema round-trip; generated TS client up to date |
| Kafka integration (Testcontainers or Compose) | duplicate delivery → one side effect; crash mid-handler → redelivered once; 3 failures → DLQ; retrier honours delay; throttled message doesn't consume attempts; outbox survives Kafka outage |
| Connectors | HubSpot sink against `respx`-mocked API; webhook signature verification; delivery idempotency |
| End-to-end | 5-call run against mock agent per planted bug (≥ 4/5 caught); Playwright smoke test of every page |
| Judge regression | 10 golden transcripts; ≤ 1 flip |

## 18. Performance budget

20-call run, 3 simulator instances: < 15 min. Platform latency overhead ≤ 50 ms. Event hop latency (produce → consume) p95 < 200 ms locally. SSE update visible in the UI < 2 s after a call is evaluated.
