# 06 — API Specification

Base URL (local): `http://localhost:8000/api/v1`. JSON everywhere except file uploads (`multipart/form-data`) and audio downloads. FastAPI also serves interactive docs at `/docs`.

**Auth:** every request needs `Authorization: Bearer pk_live_…` (an API key from `/api-keys`; `make demo` creates one). Scopes: `read`, `runs:write`, `audits:write`, `admin`. The Next.js app calls the API only from its server-side proxy, so the key never reaches the browser. Exceptions: `/health` and `/webhooks/inbound/{integration_id}` (HMAC-signed instead).

**v0.2:** async work is event-driven on Kafka, so `202` responses return the resource id to poll or stream (no job ids). New: SSE progress (§3), integrations + webhooks (§8), DLQ (§9), API keys (§10); agents use `adapter`.

**Conventions**
- IDs are UUIDs. Timestamps are ISO-8601 UTC.
- Lists support `?limit=` (default 50, max 200) and `?cursor=` (opaque); responses are `{ "items": [...], "next_cursor": "..." | null }`.
- Errors: `{ "error": { "code": "string", "message": "string", "details": {} } }` with proper HTTP status.

| Status | Code examples |
|---|---|
| 400 | `validation_error` |
| 404 | `not_found` |
| 409 | `conflict` (duplicate name, run already finished) |
| 402 | `budget_exceeded` (estimate above remaining budget) |
| 413 | `file_too_large` |
| 422 | `unsupported_audio` |
| 502 | `upstream_error` (Gnani/Gemini failed after retries) |

---

## 1. Agents

### `POST /agents`
```json
{
  "name": "EMI Reminder Bot",
  "description": "Outbound bot for Shakti Finance (fictional). Reminds customers of EMI due dates in Kannada, Hindi or English, records promise-to-pay date, never threatens, offers human transfer on request.",
  "adapter": "audio_v1",
  "adapter_config": {},
  "endpoint_url": "ws://mock-agent:8765/ws",
  "languages": ["kn-IN", "hi-IN", "en-IN"],
  "glass_box": true,
  "mandatory_disclosures": [
    { "id": "recording", "text": "This call is being recorded for quality purposes", "regex": "(record|ರೆಕಾರ್ಡ್|रिकॉर्ड)", "within_turns": 2 }
  ],
  "forbidden_phrases": [
    { "id": "threat_legal", "text": "legal action", "regex": "(legal action|police|ಪೊಲೀಸ್|पुलिस)" }
  ],
  "expected_tools": [
    { "name": "record_promise_to_pay", "description": "Save PTP date and amount" },
    { "name": "transfer_to_human", "description": "Warm transfer" }
  ],
  "bias_list": ["EMI", "UPI", "NEFT", "Shakti Finance", "ಕಂತು", "किस्त"],
  "max_call_seconds": 240
}
```
→ `201` with the full agent object (adds `id`, `created_at`, `updated_at`, `archived`).

### `GET /agents` · `GET /agents/{id}` · `PATCH /agents/{id}` · `POST /agents/{id}/archive`

### `POST /agents/{id}/test-connection`
Opens the socket, sends 1 s of silence, waits ≤ 10 s for agent audio.
```json
{ "ok": true, "first_audio_ms": 820, "protocol": "pareeksha-audio-v1", "glass_box_messages_seen": true }
```
or `{ "ok": false, "error": "timeout", "detail": "no audio within 10000 ms" }`.

### Prompt agents and versions
A prompt agent has `"adapter": "prompt"`; `endpoint_url` is optional for it. `adapter_secrets` (`{"api_key": "…"}`) is accepted on `POST /agents` and `PATCH /agents/{id}`, stored encrypted and **never returned**; responses carry `has_adapter_secrets: true|false` instead. A version is immutable; the active one is `adapter_config.active_version_id` (server-owned: ignored if a client sends it), and a run pins it in `agent_snapshot`. These routes return `409 not_a_prompt_agent` for other adapters.

### `POST /agents/{id}/prompt-versions`
```json
{
  "system_prompt": "You answer EMI questions for Shakti Finance (fictional).",
  "provider": "openai",
  "model": "gpt-4o-mini",
  "base_url": null,
  "temperature": 0.2,
  "max_tool_rounds": 5,
  "note": "first draft",
  "tools": [
    { "name": "lookup_emi", "description": "Look up the EMI",
      "parameters": { "type": "object", "properties": { "customer_id": { "type": "string" } } },
      "mock": { "mode": "static", "result": { "emi": 4200 } } }
  ]
}
```
`provider` ∈ `openai, openai_compatible, deepseek, groq, mistral, ollama, anthropic, gemini`. `mock.mode` ∈ `static` (returns `result`), `by_args` (first `cases[].when` that matches, else `result`), `simulated` (a model invents the result). → `201` with the version (adds `id`, `agent_id`, `version`, `content_hash`, `created_at`) and makes it the active one; the agent's `expected_tools` is refreshed from its tools. Identical content to the active version (the `note` is ignored) → `200` with that version, nothing created. `422 base_url_not_allowed` for private or loopback URLs unless `AGENT_LLM_ALLOW_PRIVATE_URLS=true`.

### `GET /agents/{id}/prompt-versions` · `GET /agents/{id}/prompt-versions/{version}`
List (newest first) or fetch one version by its number.

### `POST /agents/{id}/prompt-versions/{version}/activate`
Makes an existing version the active one; returns it. Runs created afterwards use it.

---

## 2. Scenarios, personas, noise profiles

### `POST /scenarios`
```json
{
  "agent_id": "…",
  "title": "Already paid, wants confirmation",
  "caller_goal": "Convince the agent you paid this month's EMI via UPI 3 days ago and get it to note your UTR number instead of demanding payment.",
  "fixtures": { "customer_name": "Ravi Kumar", "loan_id": "SHK-000123", "emi_amount": 4000, "paid_on": "3 days ago", "utr": "UTR-555-0100" },
  "reveal_rules": "Give the UTR only if asked. Give loan ID only if asked.",
  "success_criteria": "Agent asks for or accepts the UTR, does not ask for payment again, confirms it will be verified, ends politely.",
  "must_say": ["confirm the amount back to the caller"],
  "must_not_say": ["demand payment again after UTR is given"],
  "expected_tool_calls": [],
  "max_turns": 12,
  "tags": ["payment_dispute", "happy_path"]
}
```

### `POST /agents/{id}/scenarios:generate`
```json
{ "count": 10, "mix": { "happy_path": 3, "edge_case": 4, "adversarial": 3 } }
```
→ `202 { "draft_id": "…" }`. Poll `GET /scenario-drafts/{draft_id}` until `status: ready`; drafts are **not yet saved** — the web app shows them for review, then `POST /scenarios:bulk`.

### `POST /personas`
```json
{
  "name": "Manju — frustrated Kanglish auto driver",
  "language": "kn-IN",
  "code_mix_style": "heavy",
  "dialect_label": "Bengaluru urban (synthetic)",
  "tts_model": "timbre-v3.0",
  "voice_id": "Prakash",
  "speed": 1.1,
  "emotion": "frustrated",
  "patience_turns": 6,
  "interruption_level": 2,
  "silence_habit": "normal",
  "behaviour_notes": "Short sentences. Says 'sir' a lot. Gets angry if asked the same thing twice."
}
```

### `POST /personas/{id}/preview` → `audio/wav` of one sample line.

### `POST /noise-profiles`
```json
{ "name": "pstn_market_5db", "sample_rate": 8000, "codec": "alaw", "pstn_bandpass": true,
  "background_category": "market_crowd", "snr_db": 5, "packet_loss_pct": 0, "clipping": false }
```

### `POST /noise-profiles/{id}/preview` (multipart `file` optional) → degraded `audio/wav` of a sample or your clip.

Standard `GET` (list/one), `PATCH`, `DELETE` exist for all three resources. Deleting is refused (`409`) if referenced by a run.

---

## 3. Runs

### `POST /runs`
```json
{
  "agent_id": "…",
  "name": "Prompt v3 baseline",
  "kind": "matrix",
  "scenario_ids": ["…", "…"],
  "persona_ids": ["…", "…"],
  "noise_profile_ids": ["…", "…"],
  "repeats": 1,
  "config": { "max_concurrency": 3, "seed": 42, "dry_run": false }
}
```
→ `201`
```json
{
  "id": "…", "status": "queued", "item_count": 8,
  "estimate": { "tts_seconds": 240, "stt_seconds": 480, "judge_calls": 8, "caller_llm_calls": 64, "est_cost": 31.5 }
}
```
`402 budget_exceeded` if `est_cost` > remaining budget. Add `"confirm_over_budget": true` to force.

The run row and its `run.requested` event are written in one transaction; the planner then creates the items. `item_count` is computed up front so the UI can show it immediately.

Implementation notes (API-03): ids repeated in a list count once; a matrix above 1000 calls is refused with `400 validation_error` (`details: {item_count, max_items}`); an unknown or other-project agent, scenario, persona or noise profile is `404`, an archived agent `409`, a prompt agent without an active version `422 prompt_agent_has_no_version` (also on `POST /runs:estimate` and `POST /runs:regression`). The `402` body carries `details.estimate`, `details.remaining_budget` and `details.item_count`. `est_cost` is priced with the `COST_*` rates of `.env` (unset rate = 0) against `BUDGET_CREDITS` minus the `api_usage.est_cost` already spent; with no `BUDGET_CREDITS` there is no guard. `kind: dry_run` (or `config.dry_run`) is estimated without TTS or STT. The planner (`python -m pareeksha.workers.planner`, group `planner`) inserts one `run_items` row per cell with a deterministic seed and emits `call.requested` (key `run_item_id`) plus an `item.status` progress event per item. `progress.total` is `item_count` until the items exist. `POST /runs/{id}/cancel` moves queued items to `cancelled` and the run to `cancelled`; calls already in flight finish and are evaluated; a finished or already cancelled run answers `409`.

### `GET /runs/{id}/events` — live progress (Server-Sent Events)
`Content-Type: text/event-stream`. Sends a `snapshot` first, then:
```
event: item.status
data: {"run_item_id":"…","status":"in_progress","scenario":"…","persona":"…"}

event: call.evaluated
data: {"run_item_id":"…","call_id":"…","overall_score":72.5,"passed":false,"critical_failure":false}

event: run.completed
data: {"run_id":"…","summary":{"pass_rate":0.7,"critical_failures":1}}
```
Heartbeat comment every 15 s. Clients reconnect with `Last-Event-ID`; on reconnect the server sends a fresh `snapshot`.

Implementation notes (API-04): the `snapshot` is read from Postgres (`{run, items}`), the rest from `pareeksha.progress.v1` through a private group-less consumer per connection (no consumer group, no commits). Each message's `id:` is the last offset read per partition (`0:41,1:7,2:19`); with `Last-Event-ID` the server sends the fresh `snapshot` and then replays what the client missed from those offsets, so a reconnect loses nothing (events are at-least-once and can be older than the snapshot; the last one wins). Without a valid id the stream starts at the end of the topic. The stream ends after `run.completed`; a run that is already finished gets `snapshot` + `run.completed` and the stream closes. `502 upstream_error` when Kafka is unreachable.

### `POST /runs:regression`
```json
{ "agent_id": "…", "statuses": ["blocking"], "config": { "max_concurrency": 3 } }
```

### `GET /runs?agent_id=…` · `GET /runs/{id}`
```json
{
  "id": "…", "status": "running", "kind": "matrix",
  "progress": { "total": 8, "queued": 2, "in_progress": 3, "evaluated": 3, "error": 0 },
  "summary": {
    "pass_rate": 0.67, "critical_failures": 1, "needs_review": 2,
    "score_mean": 78.4, "latency_p50_ms": 1120, "latency_p95_ms": 2310,
    "barge_in_honoured_rate": 0.5,
    "top_failure_types": [["asr_misrecognition", 2], ["missing_disclosure", 1]],
    "suite_passed": null
  }
}
```

### `GET /runs/{id}/items`
Rows for the matrix view: `scenario`, `persona`, `noise_profile`, `status`, `call_id`, `overall_score`, `passed`, `critical_failure`.

### `POST /runs/{id}/cancel` → `202`.

### `GET /runs/compare?base={run_id}&head={run_id}`
```json
{
  "cells": [
    { "scenario": "Already paid…", "persona": "Manju…", "profile": "pstn_market_5db",
      "base_score": 86, "head_score": 52, "delta": -34, "newly_failing": true,
      "base_call_ids": ["…"], "head_call_ids": ["…"] }
  ],
  "summary": { "regressed": 2, "improved": 3, "unchanged": 3 },
  "base_prompt_version": 1,
  "head_prompt_version": 2
}
```
`base_prompt_version` / `head_prompt_version` are the prompt-agent versions the runs pinned (null for voice agents). A cell is (scenario title, persona name, noise profile name); repeats are averaged and a cell counts as passed only if all repeats passed. `delta = head - base` (null if either side has no evaluated call); `newly_failing` = passed in `base`, not passed in `head`. `summary` counts cells scored in both runs. Cells come worst delta first, cells without a delta last. (API-04)

### `GET /runs/{id}/report` → `text/html` exportable report.
One self-contained page (inline CSS, no scripts): summary figures, top failure types, score distribution and the matrix. Names are HTML-escaped. (API-04)

---

## 4. Calls, evaluations, audits

### `GET /calls/{id}`
```json
{
  "id": "…", "source": "simulation", "language": "kn-IN", "end_reason": "goal_achieved", "duration_ms": 84200,
  "recordings": { "mixed": "/api/v1/calls/…/audio/mixed", "caller": "…/caller", "agent": "…/agent" },
  "turns": [
    { "idx": 0, "speaker": "agent", "text": "ನಮಸ್ಕಾರ, ನಾನು ಶಕ್ತಿ ಫೈನಾನ್ಸ್‌ನಿಂದ…", "start_ms": 820, "end_ms": 5400 },
    { "idx": 1, "speaker": "caller", "text": "…", "ground_truth_text": "Sir, naanu already pay maadidini, naal-ku saavira",
      "agent_heard_text": "…naalvattu saavira…", "start_ms": 6100, "end_ms": 9300, "is_barge_in": false }
  ],
  "tool_calls": [ { "seq": 0, "name": "record_promise_to_pay", "arguments": { "amount": 40000 }, "at_ms": 11200 } ],
  "metrics": { "first_greeting_ms": 820, "response_latency_p50_ms": 1040, "response_latency_p95_ms": 2210,
               "barge_in_attempts": 2, "barge_in_honoured": 0, "silence_gaps_over_2s": 1, "caller_asr_wer": 0.18 },
  "checks": [
    { "check_type": "disclosure_present", "check_key": "recording", "passed": false, "evidence_turns": [0, 2], "detail": "No recording disclosure in first 2 agent turns" },
    { "check_type": "amount_confirmed", "check_key": "emi_amount", "passed": false, "evidence_turns": [1, 2], "detail": "Caller said 4000; agent confirmed 40000" }
  ],
  "evaluation": { "…": "see §4.1" }
}
```

### `GET /calls/{id}/audio/{track}` — `track ∈ {mixed, caller, agent, original}` → `audio/wav` (supports `Range`).
Files are read from `DATA_DIR` (`calls.recording_*` hold relative paths; a path escaping `DATA_DIR` is a 404). Single ranges (`bytes=a-b`, `a-`, `-n`) answer `206` with `Content-Range`; an unsatisfiable range is `416 range_not_satisfiable`; a multi-range or malformed header gets the whole file. A call without that track, or a missing file, is `404`. (API-04)

`GET /calls` (API-04): newest first by `started_at`; `source` repeats; `needs_review` / `reviewed` look at the call's latest evaluation (a call with no evaluation counts as `needs_review=false`, `reviewed=false`); `run_id` goes through the run item. The detail's `evaluation` is the latest evaluation row (re-evaluation adds rows).

### 4.1 Evaluation object
```json
{
  "id": "…", "rubric_version": "rubric-2026-10-v1", "judge_model": "<pinned gemini id>", "prompt_hash": "sha256:…",
  "status": "ok", "overall_score": 40.0, "passed": false,
  "critical_failure": true, "needs_human_review": true,
  "review_reasons": ["critical_failure", "check_failed:disclosure_present"],
  "failure_types": ["asr_misrecognition", "wrong_fact", "missing_disclosure"],
  "dimensions": {
    "task_completion":   { "score": 1, "evidence_turns": [2, 5], "reason": "Recorded PTP for the wrong amount." },
    "factual_accuracy":  { "score": 0, "evidence_turns": [2], "reason": "Confirmed ₹40,000 instead of ₹4,000." },
    "policy_compliance": { "score": 1, "evidence_turns": [0], "reason": "No recording disclosure." },
    "language_handling": { "score": 3, "evidence_turns": [2, 4], "reason": "Stayed in Kannada; handled English loanwords." },
    "conversation_flow": { "score": 2, "evidence_turns": [3, 4], "reason": "Talked over two interruptions." },
    "empathy_tone":      { "score": 3, "evidence_turns": [4], "reason": "Polite, acknowledged frustration once." },
    "escalation":        { "score": 4, "evidence_turns": [], "reason": "No transfer needed." }
  },
  "summary": "Misheard 'naal-ku saavira' as 40,000 and confirmed it without read-back.",
  "confidence": "high"
}
```

### `POST /calls/{id}/reevaluate` (optional `{ "rubric_version": "…" }`) → `202`.

### `PUT /calls/{id}/tool-calls` → `202 { "call_id": "…" }`
Report the tool calls the bot made, after the call (write key). Body: `{ "tool_calls": [ { "name": "record_promise_to_pay", "arguments": {}, "result": null, "at_ms": 0 } ] }` (max 200; `name` 1-200 chars). Idempotent replace of the call's trace; completed calls are re-evaluated. `404` unknown call, `409` glass-box simulated call (the live trace is authoritative).

### `POST /calls/{id}/review`
```json
{ "reviewer": "preetham", "passed": false, "critical_failure": true,
  "dimensions": { "task_completion": { "score": 1 }, "factual_accuracy": { "score": 0 } }, "notes": "Agree." }
```

### `POST /calls/{id}/promote`
```json
{ "failure_type": "asr_misrecognition", "status": "blocking", "baseline_score": 80, "notes": "Amount read-back" }
```
→ `201 { "scenario_id": "…", "regression_test_id": "…" }`

### `POST /calls/{id}/speaker-map` (uploads) `{ "spk_0": "caller", "spk_1": "agent" }` → re-evaluates.
Keys are the labels in the call's `speaker_map` (`spk_0`, `spk_1`, ... in order of first appearance); a speaker left out keeps its current role. → `202 { "call_id": "…" }`: the turns are rebuilt from the stored diarization (no new transcription) and a new `call.completed` makes the evaluator judge the call again under the same rubric version. `400` for unknown speakers or a map without both an agent and a caller, `409` for simulated calls or a call that is not `completed` yet.

### `POST /audits` (multipart)
| Field | Type | Notes |
|---|---|---|
| `file` | WAV/MP3 | ≤ 10 MB |
| `agent_id` | uuid | rubric context |
| `language` | string | e.g. `kn-IN` or `kn-IN,en-IN` |
| `stereo_channels_are_speakers` | bool | default false |

→ `202 { "call_id": "…" }`. Poll `GET /calls/{call_id}` (status `transcribing` → `completed`).

---

## 5. Dialect datasets

### `POST /dialect-datasets` `{ "name": "Kannada dialects v1", "description": "…" }`

### `POST /dialect-datasets/{id}/samples` (multipart)
- `manifest` — CSV with header: `file,reference_text,language,dialect_label,speaker_id,consent,domain_terms`
- `clips` — ZIP containing the files named in `file`

→ `200 { "accepted": 118, "rejected": [ { "row": 7, "reason": "consent must be true" } ] }`

### `POST /dialect-datasets/{id}/evaluate`
```json
{ "noise_profile_ids": ["<clean_16k>", "<pstn_8k_alaw>", "<pstn_street_10db>"], "engines": ["gnani-prisma"] }
```
→ `202 { "report_id": "…", "expected_results": 354 }`. Poll `GET /dialect-reports/{id}` (`progress.done / expected_results`).

### `GET /dialect-reports/{id}`
```json
{
  "aggregates": {
    "kn-north": { "pstn_street_10db": { "gnani-prisma": { "n": 24, "wer": 0.31, "wer_ci": [0.26, 0.37], "cer": 0.14, "entity_acc": 0.71 } } }
  },
  "top_errors": [ { "ref": "ಕಂತು", "hyp": "ಕಾಂತು", "count": 9 } ],
  "bias_suggestions": ["ಕಂತು", "NEFT", "UTR"],
  "html": "/api/v1/dialect-reports/…/html"
}
```

---

## 6. Calibration, system

| Method & path | Returns |
|---|---|
| `GET /calibration?rubric_version=…` | `{ "n": 32, "kappa_pass_fail": 0.71, "spearman_overall": 0.78, "dimension_mae": {"task_completion": 0.4, …} }` |
| `GET /usage?from=&to=` | Aggregated `api_usage` + remaining budget |
| `GET /health` | `{ "db": "ok", "kafka": "ok" }` (no auth) |
| `GET /metrics/summary` | `{ "consumer_lag": {"simulator": 4, "evaluator": 0, …}, "outbox_backlog": 0, "dlq_open": 1, "credits_used": 812.4 }` |

Implementation notes (API-04): `consumer_lag[group]` is the sum over the group's committed topic partitions of log end offset minus committed offset (a partition the group has no commit on counts from the log start); groups that never committed do not appear. `outbox_backlog` = unpublished `outbox_events`, `dlq_open` = open `dead_letters`, `credits_used` = all-time `sum(api_usage.est_cost)`. `502 upstream_error` when Kafka cannot be reached. `GET /usage?from=&to=` groups `api_usage` by provider / operation / unit type inside the window; `credits_used` is the window's cost, `budget_credits` is `BUDGET_CREDITS`, `remaining_budget` is the all-time budget left (as in the run estimate); both are null without `BUDGET_CREDITS`.

---

## 7. Agent audio protocol — `pareeksha-audio-v1`

This is what an agent under test must speak over WebSocket when its adapter is `audio_v1` (the mock agent implements it). The `pipecat`, `livekit` and `vapi` adapters translate their own transports to the same internal session, so the rest of the platform only sees this protocol's semantics (see `10-integrations-and-dx.md §4`).

**Transport:** one WebSocket per call. The platform is the **client**; the agent is the server.

**Binary frames (both directions):** raw PCM, signed 16-bit little-endian, mono, 16,000 Hz, 20 ms per frame (640 bytes). Sent at real-time pace. Silence may be sent as zero frames or omitted.

**Text frames:** JSON with a `type` field.

Platform → agent
```json
{ "type": "start", "protocol": "pareeksha-audio-v1", "call_id": "…", "sample_rate": 16000, "language_hint": "kn-IN", "metadata": {} }
{ "type": "stop", "reason": "caller_hangup" }
```

Agent → platform (all optional; sending them enables glass-box metrics)
```json
{ "type": "transcript", "role": "user",  "text": "…what the agent's STT heard…", "is_final": true, "t_ms": 9450 }
{ "type": "transcript", "role": "agent", "text": "…what the agent is about to say…", "t_ms": 9900 }
{ "type": "tool_call", "name": "record_promise_to_pay", "arguments": { "amount": 40000 }, "result": { "ok": true }, "t_ms": 11200 }
{ "type": "call_end", "reason": "completed" }
```
`t_ms` = ms since the agent received `start` (used only for ordering; the platform measures latency from its own clock).

**Lifecycle:** connect → platform sends `start` → agent normally speaks first → audio both ways → either side sends `stop`/`call_end` or closes the socket.

**Minimal agent adapter (pseudo-code)** for wrapping any existing bot:
```python
async def handler(ws):
    start = json.loads(await ws.recv())
    async for msg in ws:
        if isinstance(msg, bytes):
            await my_bot.feed_audio(msg)           # 16 kHz PCM in
        elif json.loads(msg)["type"] == "stop":
            break
    # elsewhere: for chunk in my_bot.audio_out(): await ws.send(chunk)  # 16 kHz PCM out, 20 ms frames
```

---

## 8. Integrations & webhooks

### `GET /integrations/connectors`
Installed connectors (built-in + entry-point plugins) with their JSON schemas so the web app can render forms:
```json
[ { "name": "hubspot", "direction": "sink", "subscribes_to": ["evaluation.completed"],
    "config_schema": { "...": "JSON Schema" }, "secrets_schema": { "...": "JSON Schema" } },
  { "name": "webhook", "direction": "both", "...": "..." } ]
```

### `POST /integrations`
```json
{
  "connector": "hubspot",
  "name": "HubSpot – collections portal",
  "config": { "match_by": "phone", "only_failed": false, "public_base_url": "https://pareeksha.example.com" },
  "secrets": { "private_app_token": "pat-…" },
  "event_filter": { "events": ["evaluation.completed"], "agent_ids": ["…"], "min_score_below": null }
}
```
→ `201` integration object. Secrets are write-only: responses show `"secrets_set": true`, never values. For `webhook` integrations the response includes the inbound URL and, once, the generated `signing_secret`.

`GET /integrations` · `GET /integrations/{id}` · `PATCH /integrations/{id}` (secrets replaced only if provided) · `DELETE /integrations/{id}`

### `POST /integrations/{id}/test` → `{ "ok": true, "detail": "Authenticated as portal 12345678" }`

### `GET /integrations/{id}/deliveries?status=failed`
```json
{ "items": [ { "id": "…", "event_id": "…", "direction": "outbound", "status": "succeeded",
               "http_status": 201, "external_id": "note-555", "attempts": 1, "created_at": "…" } ],
  "next_cursor": null }
```
### `POST /integrations/{id}/deliveries/{delivery_id}/redeliver` → `202`

### `POST /webhooks/inbound/{integration_id}` (no API key; HMAC-signed)
Headers: `X-Pareeksha-Timestamp`, `X-Pareeksha-Signature: v1=<hex hmac_sha256(secret, "{ts}.{raw_body}")>`.
```json
{ "external_id": "exotel-CA123", "recording_url": "https://…/CA123.mp3", "agent_name": "EMI Reminder Bot",
  "language": "kn-IN", "metadata": { "phone": "+91XXXXXXXX00", "crm_contact_id": "1234" },
  "tool_calls": [ { "name": "record_promise_to_pay", "arguments": {}, "at_ms": 0 } ] }
```
`tool_calls` is optional (same items as `PUT /calls/{id}/tool-calls`).

→ `202 { "call_id": "…", "duplicate": false }` · `401 invalid_signature` · `408 timestamp_out_of_window` · `422 unsafe_url` · `422 unknown_agent` (no agent matches `agent_name` and the integration has no `default_agent_id`). A repeated `external_id` returns the first call with `duplicate: true`; nothing new is created.

Outbound webhook payloads and signing: `10-integrations-and-dx.md §2.1`.

## 9. Dead letters

| Method & path | Returns |
|---|---|
| `GET /dlq?status=open` | `{ "items": [ { "id", "event_id", "original_topic", "consumer_group", "error", "attempts", "failed_at", "envelope" } ] }` |
| `POST /dlq/{id}/replay` | `202` — re-publishes the envelope with `attempt=1` to `original_topic` via the outbox; status → `replayed` |
| `POST /dlq/{id}/discard` | `200` — status → `discarded` |

Implementation notes (API-04): list is newest first by `failed_at`, `status` defaults to `open`. Replay re-publishes the stored envelope with `attempt=1` and the **same** `event_id` (groups that already processed it skip it through `processed_events`; if it fails again the DLQ recorder re-opens the same row); the outbox row itself gets a fresh id. Replaying or discarding a row that is not `open` is `409`, and so is replaying a message that was not a valid envelope (the recorder stores those as `{"raw": ...}`).

## 10. API keys

| Method & path | Returns |
|---|---|
| `POST /api-keys` `{ "name": "github-actions", "scopes": ["read", "runs:write"] }` | `201 { "id", "prefix": "pk_live_ab12cd34", "key": "pk_live_…full…" }` — full key shown **once** |
| `GET /api-keys` | list with prefix, scopes, last_used_at |
| `DELETE /api-keys/{id}` | revoke |

Web sign-in accounts (called only by the Next.js server with an `admin` key, which then sets its own session cookie): `GET /auth/status` returns `{ has_users }`; `POST /auth/bootstrap` creates the first admin (`409 already_bootstrapped` afterwards); `POST /auth/login` verifies email and password (`401 invalid_credentials`, `403 account_disabled`); `GET /users`, `POST /users` and `PATCH /users/{id}` manage users (`409 email_taken`, `409 last_admin`). Passwords are 10 to 200 characters (else `422 invalid_password`), stored as scrypt hashes and never returned.

## 11. Event contract (for consumers outside the API)

Kafka topics, keys and the envelope are specified in `03-TRD.md §10`. The Pydantic models in `backend/pareeksha/events/schemas.py` are the source of truth; `GET /events/schemas` returns their JSON Schemas so external consumers (e.g. a data team reading `evaluation.completed`) can validate messages.

## 13. LLM settings (per project)

The `llm_settings` row of a project overrides the environment (`LLM_PROVIDER`, `DEEPSEEK_*`, `GEMINI_*`) for that project's judge, caller, scenario generation, role detection and designer calls. DeepSeek stays the default when there is no row.

### `GET /settings/llm` (scope `read`) → `LLMSettingsOut`
`{ provider, base_url, judge_model, caller_model, designer_model, api_key_set, api_key_last4, source }`. `provider` is `deepseek`, `gemini` or `openai_compatible`; `source` is `project` or `environment` (no row: the environment's values are shown). The key is never returned.

### `PUT /settings/llm` (scope `admin`) → `LLMSettingsOut`
Body `{ provider, base_url?, judge_model?, caller_model?, designer_model?, api_key? }`. Replaces the settings. `api_key` is write-only; omit it to keep the stored key (same provider only), `""` is rejected (`400`). `openai_compatible` needs `base_url` (https, public host, no query, fragment or credentials: `422 unsafe_url` otherwise; the host is re-resolved and pinned to a public address on every LLM call), `judge_model`, `caller_model` and its own `api_key` (the environment's DeepSeek key is never sent to a custom URL). Switching provider without a key and without an environment key for that provider is `422`. `designer_model` defaults to the judge model.

### `DELETE /settings/llm` (scope `admin`) → `204`
Removes the row; the environment applies again.

### `POST /settings/llm/test` (scope `admin`) → `{ ok, provider, model, latency_ms, error }`
One tiny JSON completion with the effective settings. A provider failure is `ok=false` with a short message (never a `500`, never the key).

## 14. Test designer

### `POST /designer/chat` (scope `runs:write`) → `DesignerChatResponse`
Stateless: send the whole history each time. Body `{ messages: [{ role: user|assistant, content }], draft: DesignerDraft | null }` (1 to 40 messages, each at most 20 000 characters, at most 60 000 in total). Response `{ reply, questions: [{ id, text, options }] (0 to 5), draft: DesignerDraft | null, ready }`. The assistant (prompt `designer_v1`, project LLM settings, purpose `designer`) reads the bot prompt the user pastes, asks only what it cannot infer, then returns a draft and `ready=true` (also needs `agent.endpoint_url`); on later turns it revises `draft`. The pasted prompt is fenced as data and is never treated as instructions. Persona and noise profile ids that are not in the project are dropped (the `reply` says so); scenario tool calls must name tools of `agent.expected_tools`; regexes must compile. Invalid model output is retried once, then `502 designer_invalid_output`; provider failures are `502 upstream_error` (status code only, never the provider's text); `402 budget_exceeded` when the project budget is used up; `429 rate_limited` (20 requests per minute per key, per API process; `Retry-After`); regexes in the draft are at most 200 characters with no nested quantifiers; usage is recorded even when the call fails; no key configured is `422 llm_not_configured`.

`DesignerDraft` = `{ agent: { name, description, languages, endpoint_url|null, adapter, glass_box, mandatory_disclosures, forbidden_phrases, expected_tools, bias_list }, scenarios: [ScenarioCreate without agent_id] (1 to 30), personas: [{ existing_id } | { new: PersonaCreate }] (1 to 10), noise_profile_ids: [uuid] (1 to 8) }`.

### `POST /designer/commit` (scope `runs:write`) → `201`
Body `{ draft }`. In one transaction: creates the agent (`422` naming `draft.agent.endpoint_url` if missing, `409` on a name clash), its scenarios and the `new` personas; `existing_id` personas and noise profiles must belong to the project (`404`). Returns `{ agent_id, scenario_ids, persona_ids, noise_profile_ids, calls, run_wizard_path }` where `calls = scenarios x personas x noise profiles` and `run_wizard_path` is `/runs/new?agent=<id>&s=<ids>&p=<ids>&l=<ids>&step=review` (comma-separated ids; the run wizard reads exactly these parameters).

## 12. Additions frozen by TL-01 (page data gaps)

Added on 23 Oct 2026 after DES-01 listed API data gaps for the FR-DB-1 pages (see CHANGELOG.md). Request/response models are in the OpenAPI document; only the shape of each addition is summarised here. Auth scopes follow the same rules (reads `read`, writes `runs:write`).

| Method & path | Purpose (requirement) | Returns |
|---|---|---|
| `POST /runs:estimate` (body of `POST /runs`) | Wizard dry run: item count, cost estimate, budget check; creates nothing (FR-RN-2) | `{ item_count, estimate, remaining_budget, over_budget }` |
| `GET /runs?kind=&status=&created_from=&created_to=&agent_id=` | Runs page filters | page of runs |
| `GET /calls?source=&status=&agent_id=&run_id=&needs_review=&reviewed=` | Audits page (`source=upload&source=import`), review queue (`needs_review=true&reviewed=false`), Calibration sample source (FR-AU-*, FR-EV-7, FR-EV-8) | page of call summaries (score, passed, critical, review flags) |
| `GET /regression-tests?agent_id=&status=` | Regression page with last run result (FR-RG-1, FR-RG-2) | page of regression tests (`last_score`, `last_passed`) |
| `PATCH /regression-tests/{id}` | Change status (`blocking`/`scheduled`/`manual`/`retired`), baseline, tolerance, notes (FR-RG-1) | the regression test |
| `GET /dialect-datasets` | Dialect page dataset picker (FR-DI-1) | page of datasets with `sample_count` |
| `GET /dialect-reports?dataset_id=` | Dialect page report picker (FR-DI-4) | page of report summaries |
| `GET /dialect-reports/{id}/clips?dialect=&condition=&engine=` | Heatmap drill-down to the worst clips (FR-DB-4) | page of clip results, worst WER first |
| `GET /dialect-reports/{id}/html` | The `html` link already returned by `GET /dialect-reports/{id}` | `text/html` |
| `GET /speech/providers` | Speech provider abstraction (VOICE-07, owner-approved 2026-10-24): which of gnani / google / azure / elevenlabs / deepgram have credentials set, which are the `STT_PROVIDER` / `TTS_PROVIDER` defaults, and their capabilities; scope `read`; never returns key material | `{ items: [{ name, configured, missing_env, stt_default, tts_default, stt: {streaming, batch, word_timings, word_confidence, diarization, ...}, tts: {sample_rates, voice_listing, speed_control, ...} }] }` |

Field additions: `RunSummary.score_distribution` (10 buckets, FR-DB-2); `run_id` and `run_item_id` on the call object.
