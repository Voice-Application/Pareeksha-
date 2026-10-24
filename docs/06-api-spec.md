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
      "base_score": 86, "head_score": 52, "delta": -34, "newly_failing": true }
  ],
  "summary": { "regressed": 2, "improved": 3, "unchanged": 3 }
}
```

### `GET /runs/{id}/report` → `text/html` exportable report.

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
  "language": "kn-IN", "metadata": { "phone": "+91XXXXXXXX00", "crm_contact_id": "1234" } }
```
→ `202 { "call_id": "…", "duplicate": false }` · `401 invalid_signature` · `408 timestamp_out_of_window` · `422 unsafe_url`

Outbound webhook payloads and signing: `10-integrations-and-dx.md §2.1`.

## 9. Dead letters

| Method & path | Returns |
|---|---|
| `GET /dlq?status=open` | `{ "items": [ { "id", "event_id", "original_topic", "consumer_group", "error", "attempts", "failed_at", "envelope" } ] }` |
| `POST /dlq/{id}/replay` | `202` — re-publishes the envelope with `attempt=1` to `original_topic` via the outbox; status → `replayed` |
| `POST /dlq/{id}/discard` | `200` — status → `discarded` |

## 10. API keys

| Method & path | Returns |
|---|---|
| `POST /api-keys` `{ "name": "github-actions", "scopes": ["read", "runs:write"] }` | `201 { "id", "prefix": "pk_live_ab12cd34", "key": "pk_live_…full…" }` — full key shown **once** |
| `GET /api-keys` | list with prefix, scopes, last_used_at |
| `DELETE /api-keys/{id}` | revoke |

## 11. Event contract (for consumers outside the API)

Kafka topics, keys and the envelope are specified in `03-TRD.md §10`. The Pydantic models in `backend/pareeksha/events/schemas.py` are the source of truth; `GET /events/schemas` returns their JSON Schemas so external consumers (e.g. a data team reading `evaluation.completed`) can validate messages.

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

Field additions: `RunSummary.score_distribution` (10 buckets, FR-DB-2); `run_id` and `run_item_id` on the call object.
