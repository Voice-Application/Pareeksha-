# 03 — Technical Requirements Document (TRD) · v0.2

This document explains **how** each part is built. Diagrams: `04-system-design.md`. Tables: `05-database-design.md`. Connectors, SDK, CLI and adapters: `10-integrations-and-dx.md`.

**What changed from v0.1:** Kafka replaces the Postgres job queue (§10), Next.js replaces Streamlit (§11), and the platform is built for other teams to adopt, with a CRM connector framework (§12).

**What changed since v0.2 (reflected below):** DeepSeek is the default LLM (Gemini and OpenAI-compatible selectable, Ollama for local models); speech goes through a provider layer (`pareeksha/speech/`: Gnani default, Google, Azure, ElevenLabs, Deepgram); prompt-based agents tested over text (`agent_llm/`, `simulation/text_runner.py`); quick tests; RAG lab (knowledge bases, `indexer`, `rag/`); designer; user accounts and sessions; per-project LLM settings and pricing; `reconciler` and `judge` workers; LiveKit and Vapi adapters are **not built**.

> ✅ Gnani endpoints, auth header, model names, voices and language codes were **checked against the published `gnani-vachana` 0.8.2 package** (23 Oct 2026); the Gnani code path now uses `gnani-vachana` only (`pipecat-gnani` is no longer a dependency). Behaviour (latency, accuracy, optional headers, credit cost) is still unverified unless noted in `NOTES.md`.

---

## 1. Tech stack

Versions are the lower bounds in `backend/pyproject.toml`, root `requirements.txt` and `web/package.json`.

| Layer | Choice | Why |
|---|---|---|
| Backend language | Python 3.11 / 3.12 (Docker image: 3.12) | Pipecat, Gnani SDK, audio libs; `audioop` built in (3.13 needs `audioop-lts`) |
| API | FastAPI + Uvicorn | Async, OpenAPI spec is the contract for the web app and SDK |
| Data models | Pydantic v2 | API schemas, event schemas, LLM structured output |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic, `psycopg` 3 | Migrations `0001`–`0007` |
| System of record | PostgreSQL 16 | Agents, runs, calls, scores, integrations, users, knowledge bases |
| **Event backbone** | **Apache Kafka 4.0 (KRaft mode, no ZooKeeper)** | Durable event log between pipeline stages; scale by adding consumers; replay; fits v2 live-call streaming |
| Kafka client | **aiokafka** (≥ 0.11 in `pyproject.toml`, ≥ 0.14 in root `requirements.txt`) | asyncio-native, matches the rest of the backend |
| Real-time audio | Pipecat ≥ 1.13 (`pipecat-ai[silero]`; `[websocket]` extra for the serializer/examples) | Frame pipeline, Silero VAD, WebSocket transports |
| Gnani SDK | `gnani-vachana` ≥ 0.8.2 | REST/stream/batch STT, TTS |
| STT / TTS providers | `pareeksha/speech/` behind `STT_PROVIDER` / `TTS_PROVIDER`: `gnani` (default), `google`, `azure`, `elevenlabs`, `deepgram` | Gnani Prisma/Timbre is India-trained and 8 kHz-aware; others are plain HTTP clients (`google-auth` for Google) |
| TTS | Gnani Timbre **v3.0** by default (13 voices, every voice speaks all 10 languages) | v2.5 has only 2 Kannada voices |
| LLM | `LLM_PROVIDER=deepseek` (default; OpenAI-compatible API, judge `deepseek-v4-pro`, caller `deepseek-flash`) or `gemini`; per-project override incl. `openai_compatible`; plain `httpx` clients (no vendor SDK) | Caller brain, judge, scenario generation, designer |
| Agent-under-test LLMs | `pareeksha/agent_llm/` (OpenAI-compatible, Anthropic, Gemini) | Prompt agents tested over text |
| Embeddings / rerank | `fastembed` (local ONNX models), plus OpenAI-wire providers incl. Ollama (`OLLAMA_BASE_URL`); `pypdf` for PDF extraction; own BM25 | RAG lab |
| Audio DSP | numpy, scipy.signal, soundfile, `audioop` | Exact SNR, bandpass, A-law round trip; noise beds are synthesised in code |
| Text metrics | rapidfuzz; WER/CER, numeral and loanword normalisation implemented in `dialect/` and `evaluation/` | Fuzzy checks, Indic normalisation |
| **Web app** | **Next.js 16 (App Router) + React 19 + TypeScript + Tailwind 4 + shadcn-style components (`components/ui`) + lucide-react** | Production-grade UI |
| Web data | TanStack Query 5, `openapi-typescript` 7 + `openapi-fetch` (generated, typed client) | API types never drift from the backend |
| Web media/charts | Custom waveform (peaks drawn from the call audio) and in-repo SVG charts (`components/charts`) | Evidence-turn seeking, heatmaps, latency charts |
| Live updates | Server-Sent Events from FastAPI | One-way progress stream; simpler than WebSockets |
| SDK / CLI | `pareeksha-sdk` (httpx, pydantic, PyYAML) + Typer CLI | Others adopt it from their own code and CI |
| Secrets at rest | `cryptography` Fernet with `SECRET_KEY` | Encrypt connector tokens, agent/KB/LLM keys |
| Logging | stdlib `logging` with a JSON formatter (`events/runtime.py`) | Correlation IDs |
| Tests | pytest, pytest-asyncio, respx, Playwright (+ axe-core) | Unit, contract, Kafka, e2e |
| Packaging | Docker Compose | `docker compose up` = whole stack (workers sit behind the `workers` profile; `kafka-ui` behind `tools`; `ollama` behind `ollama`) |

---

## 2. Processes

| Process | Command | Consumer group | Responsibility |
|---|---|---|---|
| `api` | `uvicorn pareeksha.api.main:app` | — (producer via outbox; SSE reader) | REST, uploads, webhooks in, writes rows + outbox events |
| `migrate` | `sh /app/alembic_migrate.sh` | — | One-shot Alembic upgrade before `api` starts |
| `outbox-relay` | `python -m pareeksha.workers.outbox_relay` | — | Publishes unpublished `outbox_events` rows to Kafka; prunes old published rows |
| `planner` | `python -m pareeksha.workers.planner` | `planner` | `run.requested` → expand matrix → `call.requested` × N |
| `simulator` | `python -m pareeksha.workers.simulator` | `simulator` | Runs a simulated call (Pipecat voice pipeline, or the text runner for prompt agents) → `call.completed` |
| `auditor` | `python -m pareeksha.workers.auditor` | `auditor` | Uploaded/imported recording → batch STT → turns → `call.completed` |
| `evaluator` | `python -m pareeksha.workers.evaluator` | `evaluator` | Metrics + checks + judge + scoring → `evaluation.completed` |
| `finalizer` | `python -m pareeksha.workers.finalizer` | `finalizer` | Updates run summary; when all items done → `run.completed` |
| `reconciler` | `python -m pareeksha.workers.reconciler` | — (timer loop) | Every minute: heals leaked `active_calls` slots, gives up dead-lettered / stale run items |
| `judge` | `python -m pareeksha.workers.judge` | — (timer loop; `JUDGE_WORKER_ENABLED=1`) | Judges finished quick-test calls without a client polling |
| `integrations` | `python -m pareeksha.workers.integrations` | `integrations` | Fans events out to sink connectors (HubSpot, webhook) |
| `dialect` | `python -m pareeksha.workers.dialect` | `dialect` | Clip × condition ASR eval; aggregate when dataset done |
| `generator` | `python -m pareeksha.workers.generator` | `generator` | LLM scenario generation |
| `indexer` | `python -m pareeksha.workers.indexer` | `indexer` | `kb.index.requested` → chunk, embed, store `kb_chunks`, mark the index `ready`/`failed` |
| `retrier` | `python -m pareeksha.workers.retrier` | `retrier` | Moves due messages from retry topics back to their target topic |
| `dlq-recorder` | `python -m pareeksha.workers.dlq_recorder` | `dlq-recorder` | Copies DLQ messages into `dead_letters` for the UI/replay |
| `web` | `next start` (in `web/`) | — | Dashboard; talks only to the API via its own server-side proxy |
| `mock-agent` | `python -m mock_agent.server` | — | Demo target bot |
| `kafka`, `kafka-init`, `postgres` | images / one-shot topic creation | — | Infrastructure |
| `kafka-ui`, `ollama` | optional (`tools` / `ollama` profiles) | — | Kafka browser; local model server for embeddings and agent LLMs |

All Python workers share one image (`backend/Dockerfile`) and the consumer framework (`pareeksha.events.consumer`, `run_worker(group)`), so a new stage is one handler function plus one line in Compose.

---

## 3. Speech: Gnani and other providers (`pareeksha/gnani/`, `pareeksha/speech/`)

`pareeksha/speech/` defines provider-neutral `STTProvider` / `TTSProvider` interfaces and a registry (`get_stt_provider()`, `get_tts_provider()`); selection order is an explicit name, then the per-agent `SpeechSelection`, then `STT_PROVIDER` / `TTS_PROVIDER` (default `gnani`). Providers: `gnani`, `google`, `azure`, `elevenlabs`, `deepgram` (`speech/providers/`). The caller pipeline's `AgentSTT` / `CallerTTS` use these interfaces.

The Gnani provider wraps **`gnani-vachana`** (`pareeksha/gnani/clients.py`, class `GnaniSpeech`): `GnaniSTTClient` (REST), `GnaniSTTStreamClient` (WS), batch client (`gnani.stt.batch_async`), `GnaniTTSClient` / `GnaniTTSStreamClient`. The repo does not import `pipecat-gnani`.

Confirmed from SDK source:
- Base `https://api.vachana.ai`; header `X-API-Key-ID`; STT `/stt/v3`, `/stt/v3/stream`; TTS `/api/v1/tts`, `/api/v1/tts/inference`, `/api/v1/tts/sse`.
- Languages: `bn-IN en-IN gu-IN hi-IN kn-IN ml-IN mr-IN pa-IN ta-IN te-IN`; TTS also accepts `auto`. **No separate Hinglish/Kanglish code** — send code-mixed text with the base language or `auto`.
- TTS models `timbre-v2.0`, `timbre-v2.5` (SDK default), `timbre-v3.0` (Pareeksha default, `GNANI_TTS_MODEL`). Encodings `linear_pcm`, `oggopus`, `pcm_mulaw`, `pcm_alaw`; sample rates 8000–48000.
- v2.5 Kannada voices: Saanvi, Kavin. v3.0 voices (all languages): Avinash, Shivani, Lakshmi, Kalpana, Shubham, Prakash, Devansh, Yashraj, Chetana, Vasudha, Riyaa, Tarika, Harshad.

Still unverified here: telephony tuning headers (`STT_VAD_THRESHOLD`, `STT_MIN_SILENCE_MS` are configured but header support is unconfirmed), batch diarization/denoise option names, credit cost.

Rules: every call logs `api_usage` (`UsageLedger`; `provider` is one of gnani/gemini/deepseek/google/azure/elevenlabs/deepgram/other); 5xx/timeouts retried with exponential backoff (cap 8 s); TTS disk cache keyed by request parameters and text (`TTS_CACHE_MAX_MB`); batch results downloaded immediately (URLs expire).

## 4. LLM module (`pareeksha/llm/`)

`LLMProvider` implementations (`deepseek.py`, `gemini.py`, OpenAI-compatible) behind `build_provider` / `build_client` (`factory.py`). `LLMClient.generate_json(...)` gives structured output, one repair retry on validation failure, usage logging (`usage_db.py`) and an optional JSON cache. Provider, models and key come from the environment (`LLM_PROVIDER`, default `deepseek`) and can be overridden per project (`llm_settings`, `PUT /settings/llm`, applied without a restart). Versioned Jinja2 prompts in `pareeksha/llm/prompts/`: `caller_v1`, `judge_v1`/`v2`/`v3`, `scenario_gen_v1`, `role_detect_v1`, `asr_intent_v1`, `designer_v1`, `assistant_v1`, `quick_test_plan_v1`, `quick_test_judge_v1`, `quick_test_improve_v1`, `rag_judge_v1`, `rag_questions_v1`; `prompt_hash` = sha256 of the unrendered template.

| Use | Temperature |
|---|---|
| Judge, role detection, ASR intent | 0 (`JUDGE_TEMPERATURE`) |
| Caller brain | 0.7 (`CALLER_TEMPERATURE`; the opening utterance is sampled at 0) |
| Scenario generation | 0.8 |
| Designer chat | 0.2 (`DESIGNER_TEMPERATURE`) |

---

## 5. Simulation engine (`pareeksha/simulation/`)

Runs inside the `simulator` consumer (`CallRunner` for voice agents; `text_runner.run_text_call` for `prompt` agents, which talks to the customer's model through `agent_llm/` with mocked tool results and optional RAG retrieval and returns the same `CallResult`).

```
agent ─► AgentSource ─► CallTap ─► AgentTurnDetector ─► AgentSTT ─► CallerDirector ─► CallerTTS ─► CallerMic ─► agent
                            (Silero VAD)              (STTProvider)  (LLM caller brain)   (TTSProvider +
                                                                                            LineSimulator)
                         recorder taps both directions
```

| Processor | Job |
|---|---|
| `AgentSource` | Reads audio from the adapter session into the pipeline |
| `CallTap` | Monotonic timestamps on every frame → recorder + event log |
| `AgentTurnDetector` | Silero VAD (`EnergyVADAnalyzer` fallback in `vad.py`) → detects agent speech start/end |
| `AgentSTT` | Caller-side recognition of the agent's speech via any `STTProvider` |
| `CallerDirector` | Calls the caller brain (`llm/caller.py`: persona + scenario + history → `{utterance, end_call, goal_status, notes}`), handles hello/nudge/hang-up, drives barge-in |
| `CallerTTS` | Persona voice/speed via `TTSProvider`, then `LineSimulator` degrades it |
| `CallerMic` | Sends speech or silence to the agent on a drift-free 20 ms clock |
| `BargeInScheduler` | Interrupts at seeded 0.8–2.5 s into an agent turn (p = 0, .25, .5, .8 by level) |
| `TurnTracker` | Builds turns and the glass-box transcript / tool_call / call_end messages |

Transports: the agent is reached through an **adapter** (`pareeksha/adapters/`, `agents.adapter`): `audio_v1` (native protocol) and `pipecat` (Pipecat serializer) are built; `livekit` and `vapi` are valid enum values but **not built** (`adapters/registry.py` rejects them); `prompt` agents bypass adapters and use the text runner. See `10-integrations-and-dx.md §4`.

Turn-taking valves (`SimulationSettings`): agent speaks first by default; caller says "Hello?" after 6 s of silence; one nudge after 8 s mid-call silence, then `agent_silent`; per-agent `max_call_seconds` (10–1800 s); max turns from scenario; audio sent at real-time pace; persona `silence_habit` adds long pauses or going silent.

Latency = agent VAD speech start − caller last frame sent (single monotonic clock, includes network; platform overhead measured against an echo agent, target ≤ 50 ms). Barge-in honoured = agent silent ≥ 300 ms within 1500 ms of caller starting. Recording: caller (degraded) + agent tracks at 16 kHz mono + aligned stereo mix.

## 6. Line simulator (`pareeksha/audio/`)

Per 20 ms chunk at 16 kHz: float32 → resample to profile rate → 300–3400 Hz Butterworth bandpass (stateful) → background noise at SNR measured on **speech-active** samples (`noise × sqrt(Ps / (Pn · 10^(SNR/10)))`) → optional clipping → **G.711 A-law** round trip (Indian PSTN; µ-law optional) → optional packet loss (drop 20 ms frames) → resample back to 16 kHz. Seeded RNG; chunked output == whole-file output. Background noise beds are **procedurally synthesised** per category (`audio/noise.py`; no licensed clips, no `data/noise/`). 8 built-in profiles (`audio/profiles.py`).

## 7. Evaluation engine (`pareeksha/evaluation/`)

Runs in the `evaluator` consumer for every `call.completed`:
1. Snapshot (masked turns, metrics, tool trace, goals) → 2. deterministic metrics → 3. deterministic checks (disclosure, forbidden, language match, tool calls, loops, amount read-back, no unexpected tool call) → 4. LLM judge (rubric in `08`; active rubric version from `rubric_versions`, seeded v1–v3) → 5. scoring **in code** + forced review rules → 6. save evaluation + `processed_events` row in one transaction → 7. produce `evaluation.completed`. For calls with retrievals, RAG metrics are computed into `rag_metrics`.

PII masking before the judge: Indian mobile, Aadhaar-like, PAN-like, email, card-like numbers. `calls.metadata` (customer phone/email for CRM matching) is **never** included in judge input.

## 8. Post-call audit (`pareeksha/audit/`)

Triggered by `audit.requested` (from `POST /audits`, the inbound webhook connector, or future source connectors). Download/convert → batch STT via the configured STT provider (Gnani: 2-speaker diarization, denoise, agent `bias_list`) → role detection (first speaker + LLM check) → turns → `call.completed`. Imported calls are deduplicated by `external_refs (integration_id, external_id)`.

## 9. Dialect pipeline (`pareeksha/dialect/`)

`POST /dialect-datasets/{id}/evaluate` writes one `dialect.clip.requested` per clip × condition (key = sample_id, so clips spread across partitions). The `dialect` consumer degrades the clip offline with the same `LineSimulator`, transcribes with the STT provider, normalises (NFC, numerals incl. lakh/crore, loanword script unification via `loanwords.yaml`), computes WER/CER/entity accuracy/intent. When the count of `asr_results` reaches the expected total, it aggregates (speaker-grouped bootstrap CIs, top substitutions, `bias_list` suggestions) and writes `dialect_reports`.

## 9a. Knowledge bases, quick tests, designer

- **RAG lab** (`pareeksha/rag/`, routers `knowledge_bases`, `rag_matrices`): documents are extracted (`pypdf` for PDF), chunked, embedded (local `fastembed` models, Ollama or hosted OpenAI-wire providers; `local_only` KBs require local embedding/rerank endpoints (`rag/guard.py`)) and stored in `kb_chunks` by the `indexer` consumer (`kb.index.requested`). The retriever supports BM25, dense, hybrid, rerank and MMR, query transforms and small-to-big context; per-turn results land in `retrievals`, metrics in `rag_metrics`, and RAG-lab comparisons in `rag_matrices`. Prices come from built-in rates plus `price_overrides`.
- **Prompt agents** (`agents.adapter = 'prompt'`, `prompt_versions`): system prompt + model + tools + optional RAG config, tested over text; the SDK/CLI can push versions (`pareeksha prompt push|versions|activate`).
- **Quick tests** (`pareeksha/quicktest/`, `quick_tests`): paste a prompt; scenarios are planned from its rules and run as an ordinary prompt-agent run; per-call rule verdicts are filled when the test is read (or by the `judge` worker), and an improved prompt is re-tested as a new prompt version on the same scenarios.
- **Designer** (`pareeksha/designer/`, `designer` router, `designer_v1.j2`): one LLM chat turn builds a prompt, validates and cleans the answer to help author tests.

---

## 10. Event backbone — Kafka

### 10.1 Cluster
- Local: single-broker KRaft (`apache/kafka:4.0.0` image), replication factor 1, `auto.create.topics.enable=false`; a one-shot `kafka-init` container creates topics.
- Production-ready path: 3 brokers, RF 3, `min.insync.replicas=2`, managed Kafka (Confluent Cloud, Aiven, MSK). Note: the code connects with `KAFKA_BOOTSTRAP_SERVERS` only; the `KAFKA_SECURITY_PROTOCOL` / `KAFKA_SASL_*` entries in `.env.example` are not read yet, so SASL/TLS support would need a code change.

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
| `pareeksha.kb.index.requested.v1` | kb_id | api (outbox) | indexer | 3 |
| `pareeksha.retry.30s.v1` | original key | any consumer | retrier | 3 |
| `pareeksha.retry.5m.v1` | original key | any consumer | retrier | 3 |
| `pareeksha.dlq.v1` | original key | any consumer | dlq-recorder | 3 |

> **Why `call.requested` is keyed by run_item_id, not run_id:** keying by run_id would put a whole run on one partition, so only one simulator could process it at a time. Keying by item spreads a run across partitions; the per-run concurrency cap is enforced separately (§10.6).

Retention 7 days (progress topic: 1 day, `dlq` topic: 30 days). Partition count is the ceiling on parallel consumers per group — 6 is plenty for v1 and can be raised later (only the key→partition mapping changes, which no consumer relies on for ordering across items).

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
5. Long jobs: the default `max_poll_interval_ms` is 300000 (5 min); `auditor` sets 900000 (15 min) and `simulator` 2400000 (40 min); a call is capped by the agent's `max_call_seconds` (default 300 s, max 1800 s).
6. Graceful shutdown on SIGTERM: stop polling, finish the current message, commit, leave group.

**Retrier:** consumes both retry topics; for each message, waits until `x-not-before` (pausing the partition; messages in one delay topic are already in due-time order), produces to `x-target-topic`, commits.

**DLQ:** `dlq-recorder` copies messages into `dead_letters`. `POST /dlq/{id}/replay` (or `pareeksha dlq replay`) re-publishes the original envelope with `attempt=1` to its original topic via the outbox.

### 10.6 Back-pressure and concurrency
- Global: number of `simulator` instances (Compose `deploy.replicas`, default 3).
- Per run: before starting a call, `UPDATE test_runs SET active_calls = active_calls + 1 WHERE id = :run AND active_calls < (config->>'max_concurrency')::int RETURNING id`. No row → the run is at its cap: send the message to `retry.30s` **without** incrementing `attempt` (header `x-reason: throttled`). Decrement in the same transaction that saves the finished call. The `reconciler` worker recomputes `active_calls` from `run_items` every minute to heal crashes and gives up run items that nothing will move on any more (dead-lettered or stale; `runs/watchdog.py`).
- Per agent rate limit: v2.

### 10.7 Delivery guarantees (what to tell a reviewer)
At-least-once delivery + idempotent consumers (`processed_events`, unique constraints, upserts) = effectively-once side effects in Postgres. External side effects (HubSpot, webhooks) are guarded by `integration_deliveries UNIQUE (integration_id, event_id, direction)`. Kafka transactions/EOS are deliberately not used: they don't cover Postgres or HTTP side effects anyway.

---

## 11. Web app (`web/`)

- **Next.js 16 App Router**, TypeScript strict, Tailwind 4, shadcn/ui components, lucide icons.
- **Server-side proxy (BFF):** browser calls `web/app/api/proxy/[...path]/route.ts`, which forwards to FastAPI with the API key from server env. The key never reaches the browser (NFR-8). SSE is streamed through the same proxy.
- **Typed client:** `npm run gen:api` (`web/scripts/gen-api.mjs`; `gen:api:check` in CI) generates `lib/api/schema.d.ts` from the API's OpenAPI; `openapi-fetch` + TanStack Query hooks wrap it. CI fails if the generated file is stale.
- **Live progress:** `GET /api/v1/runs/{id}/events` (SSE) — events `snapshot`, `item.status`, `call.evaluated`, `run.completed` (plus heartbeat comments); the run page patches its state on each event and falls back to 5 s polling if SSE drops.
- **Call detail:** in-repo waveform (peaks computed from the caller/agent audio, `components/calls/audio-panel.tsx`), transcript synced to playback, clicking an evidence turn seeks audio, judge dimensions with reasons, deterministic checks, promote-to-regression dialog.
- **Charts:** in-repo SVG chart components (`components/charts`) and heatmaps (scenario × persona, dialect × condition), latency charts.
- **Auth:** user accounts (`users`, scrypt password hashes; roles `admin`/`member`). The first visit to `/login` creates the admin; sessions are HMAC-signed cookies keyed by `SESSION_SECRET`, enforced by `web/proxy.ts` (Next 16 name for middleware); `/welcome`, `/login` and `/api/auth/*` are open; `AUTH_DISABLED=1` is for local development/tests only. The proxy attaches the server-side API key.
- Pages (`web/app/(dashboard)/`): overview, agents, scenarios, personas, noise profiles, designer, runs (new, detail, compare), calls, quick tests (`test/`), audits, dialect, regression, calibration, knowledge bases, RAG lab, integrations, DLQ, settings (api-keys, llm, pricing, users); public landing at `/welcome`.
- Pages and wireframe requirements: `02-requirements.md §1.10` and the designer's spec (AGENTS.md task DES-01).

## 12. Integrations & developer experience

Summary here; full spec in `10-integrations-and-dx.md`.
- **Connector framework** (`pareeksha/integrations/`): one module per connector implementing `Connector` (`name`, `direction`, `config_schema`, `test()`, `handle(event)` for sinks, `ingest(request)` for sources). Registered through the Python entry-point group `pareeksha.connectors`, so a third party can `pip install pareeksha-connector-zoho` without touching core code. Secrets Fernet-encrypted.
- **v1 connectors:** Generic Webhook (source + sink, HMAC-signed), HubSpot (sink: note on the matched contact with score, pass/fail, failure types, summary and link).
- **SDK + CLI:** `pip install pareeksha-sdk` → `Pareeksha(api_key).runs.create(...)`, CLI `pareeksha login|apply|run|regress|audit|dlq|doctor`, plus `prompt` (push/versions/activate/set-key), `kb` (create/set-keys/upload/index), `questions` and `rag` (run/report/pricing/set-price) groups.
- **Config-as-code:** `pareeksha.yaml` in the user's repo (agent, scenarios, personas, profiles) → `pareeksha apply`.
- **GitHub Action:** runs the regression suite on PRs that touch prompts; fails below threshold.
- **Agent adapters:** native `audio_v1` and Pipecat are built; LiveKit and Vapi are not (the registry rejects them); `prompt` agents use the text runner.
- **API keys** with scopes for all programmatic access.

---

## 13. Configuration

`.env.example` is the reference (read via environment variables and `pydantic-settings`). Notable settings: `LLM_PROVIDER` (default `deepseek`) + provider keys/models, `STT_PROVIDER` / `TTS_PROVIDER` + per-provider keys, `KAFKA_BOOTSTRAP_SERVERS`, `TOPIC_PARTITIONS` (read by `kafka-init`), `SECRET_KEY` (Fernet), `SESSION_SECRET` (web session cookies; required), `PAREEKSHA_API_KEY` (web server → API), `PAREEKSHA_API_URL`, `PUBLIC_BASE_URL` / `PUBLIC_API_URL` (links), `OLLAMA_BASE_URL`, `JUDGE_WORKER_ENABLED`, `SIMULATOR_REPLICAS` / `EVALUATOR_REPLICAS`, `AGENT_ALLOW_PRIVATE_ENDPOINTS`, `BUDGET_CREDITS`. `WEB_PASSWORD` is superseded by user accounts.

## 14. Error handling

| Failure | Behaviour |
|---|---|
| Agent unreachable | Retryable → retry.30s → retry.5m → DLQ; run item `error` after attempt 3 |
| Agent hangs up mid-call | Not an error; call saved, `end_reason=agent_hangup`, evaluated |
| Speech/LLM provider 5xx / timeout | Client retries with backoff, then retryable error → retry topics |
| Provider 4xx, invalid judge JSON after repair | Permanent → DLQ (evaluation stored as `judge_error`) |
| Kafka down | API keeps accepting (outbox buffers); workers reconnect with backoff |
| Postgres down | Consumers stop committing offsets; messages are redelivered when it returns |
| Worker crash | Group rebalance → message redelivered → idempotency check |
| HubSpot rate limit (429) | Retryable with `Retry-After` honoured |
| Budget exceeded mid-run | Remaining items `skipped_budget`; run `partial` |

## 15. Observability

JSON logs (stdlib `logging` with a JSON formatter; `LOG_JSON` in `.env.example` is not read by the code) with `event_id`, `correlation_id`, `run_id`, `call_id`, consumer group. Per-call `event_log`. `/health` checks DB + Kafka metadata. `/metrics/summary`: consumer lag per group (via admin client), outbox backlog, DLQ open count, credits used. Optional `kafka-ui` (kafbat) container behind the `tools` Compose profile.

## 16. Security & privacy

Secrets in env; connector secrets Fernet-encrypted; API keys stored as sha256 hashes with scopes; outbound webhooks HMAC-signed with timestamp (replay window 5 min); inbound webhooks verified the same way; SSRF guard on recording URLs (https only, block private IP ranges); uploads MIME-sniffed and size-limited; PII masked before the judge; CRM pushes contain no transcript by default; synthetic fixtures only.

## 17. Testing strategy

| Level | What |
|---|---|
| Unit | DSP (SNR, bandpass, codec, determinism), text normalisation, numerals, WER, PII, scoring, kappa, HMAC sign/verify, connector config validation |
| Contract | Gnani clients vs recorded fixtures; OpenAPI snapshot; event schema round-trip; generated TS client up to date |
| Kafka integration (against the Compose `kafka` + `postgres`; `backend/tests/kafka`, CI `kafka-suite.yml`) | duplicate delivery → one side effect; crash mid-handler → redelivered once; 3 failures → DLQ; retrier honours delay; throttled message doesn't consume attempts; outbox survives Kafka outage |
| Connectors | HubSpot sink against `respx`-mocked API; webhook signature verification; delivery idempotency |
| End-to-end | 5-call run against mock agent per planted bug (≥ 4/5 caught); Playwright smoke test of every page |
| Judge regression | 10 golden transcripts; ≤ 1 flip |

## 18. Performance budget

20-call run, 3 simulator instances: < 15 min. Platform latency overhead ≤ 50 ms. Event hop latency (produce → consume) p95 < 200 ms locally. SSE update visible in the UI < 2 s after a call is evaluated.
