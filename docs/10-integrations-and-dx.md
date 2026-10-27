# 10 — Integrations & Developer Experience · v0.2

Goal: another team can plug Pareeksha into **their** stack in under 30 minutes: run it, connect their bot, send it recordings, and get results back in their CRM or CI.

| Need | What we ship in v1 | Status |
|---|---|---|
| Run it | `docker compose up` + `make demo` | Must |
| Connect a bot | Native `pareeksha-audio-v1` adapter + Pipecat adapter | Must |
| | LiveKit adapter | Should |
| | Vapi adapter | Could |
| Drive it from code | `pareeksha-sdk` (Python) + CLI | Must |
| Keep tests in their repo | `pareeksha.yaml` + `pareeksha apply` | Should |
| Gate releases | GitHub Action | Should |
| Send calls in | Generic Webhook **source** (signed) | Must |
| Send results out | Generic Webhook **sink** (signed) + **HubSpot** sink | Must |
| Other CRMs | Salesforce, Zoho CRM, LeadSquared, Freshdesk, Exotel source, Slack sink | Designed for, not built |

---

## 1. Connector framework (`pareeksha/integrations/`)

### 1.1 Interface (frozen contract)

```python
from typing import ClassVar, Literal, Protocol
from pydantic import BaseModel

class TestResult(BaseModel):
    ok: bool
    detail: str = ""

class InboundRequest(BaseModel):
    headers: dict[str, str]
    body: bytes
    integration_id: str

class AuditRequest(BaseModel):          # what a source turns an inbound call into
    recording_url: str
    agent_id: str | None = None
    agent_name: str | None = None
    language: str                       # e.g. "kn-IN" or "kn-IN,en-IN"
    external_id: str                    # dedupe key in external_refs
    metadata: dict[str, str] = {}       # phone/email/crm ids for matching on the way back

class Connector(Protocol):
    name: ClassVar[str]                              # "hubspot"
    direction: ClassVar[Literal["source", "sink", "both"]]
    config_schema: ClassVar[type[BaseModel]]         # non-secret settings
    secrets_schema: ClassVar[type[BaseModel]]        # tokens etc. (encrypted at rest)
    subscribes_to: ClassVar[list[str]]               # sinks: event types, e.g. ["evaluation.completed"]

    async def test(self, config, secrets) -> TestResult: ...
    # sink: react to a platform event (must be idempotent; framework records the delivery)
    async def handle(self, event: "Envelope", config, secrets, ctx: "DeliveryCtx") -> "DeliveryOutcome": ...
    # source: turn an inbound webhook (or a poll, later) into audit requests
    async def ingest(self, request: InboundRequest, config, secrets) -> list[AuditRequest]: ...
```

### 1.2 Registration
Connectors are discovered via the entry-point group **`pareeksha.connectors`**:

```toml
# pyproject.toml of a third-party package, e.g. pareeksha-connector-zoho
[project.entry-points."pareeksha.connectors"]
zoho = "pareeksha_connector_zoho:ZohoConnector"
```
`pip install pareeksha-connector-zoho` + restart = the connector appears in `GET /integrations/connectors` and the web app's "Add integration" list. Built-ins register the same way.

### 1.3 What the framework does for every connector
- Validates `config` / `secrets` with the connector's schemas; encrypts secrets (Fernet, `SECRET_KEY`).
- **Sinks:** the `integrations` consumer reads `evaluation.completed` and `run.completed`, finds enabled sink integrations whose `event_filter` matches (event type, agent IDs, `only_failed`, `min_score_below`), inserts an `integration_deliveries` row (`UNIQUE (integration, event, outbound)` → no double posting), calls `handle`, records status/HTTP code/external id. Retryable failures (timeouts, 5xx, 429 with `Retry-After`) go through the standard retry topics; after 3 attempts → DLQ.
- **Sources:** `POST /webhooks/inbound/{integration_id}` → verify → `ingest` → dedupe on `external_refs` → create `calls` row (`source=import`, `metadata`) + `audit.requested` via outbox, all in one transaction.
- `POST /integrations/{id}/test` → `test()`; result stored in `last_test_ok`.
- Delivery log in the web app (last 100 deliveries, status, response excerpt, "redeliver" button).

### 1.4 Data minimisation
Sinks receive an `EvaluationSummary` (call id, agent, scenario/persona if simulated, score, passed, critical, failure types, judge summary, top 3 failing dimension reasons, deep link, `call.metadata`). **No transcript or audio** unless the integration's config sets `include_transcript: true`.

---

## 2. v1 connectors

### 2.1 Generic Webhook — source + sink

**Signing (both directions, Stripe-style):**
```
X-Pareeksha-Timestamp: 1761478500
X-Pareeksha-Signature: v1=<hex(hmac_sha256(secret, f"{timestamp}.{raw_body}"))>
```
Receivers reject timestamps older than 5 minutes and compare with constant-time equality. Secret rotation: two active secrets allowed (`v1=...,v1=...`).

**Sink (outbound) payload** — one POST per matching event:
```json
{
  "event_id": "…", "type": "evaluation.completed", "occurred_at": "…",
  "data": {
    "call_id": "…", "agent": {"id": "…", "name": "EMI Reminder Bot"},
    "source": "import", "external_id": "exotel-CA123",
    "overall_score": 40.0, "passed": false, "critical_failure": true,
    "failure_types": ["asr_misrecognition", "wrong_fact"],
    "summary": "Misheard 4,000 as 40,000 and confirmed it.",
    "link": "https://pareeksha.example.com/calls/…",
    "metadata": {"phone": "+91XXXXXXXX00"}
  }
}
```
Config: `url` (https only), `events`, `only_failed`, `include_transcript`, `timeout_s`. Secrets: `signing_secret`.

**Source (inbound)** — `POST /webhooks/inbound/{integration_id}`:
```json
{
  "external_id": "exotel-CA123",
  "recording_url": "https://recordings.example.com/CA123.mp3",
  "agent_name": "EMI Reminder Bot",
  "language": "kn-IN",
  "metadata": {"phone": "+91XXXXXXXX00", "crm_contact_id": "1234"}
}
```
→ `202 {"call_id": "…", "duplicate": false}`. Recording URL guard: https only, DNS-resolved IP must not be private/loopback/link-local, max 10 MB, content-type audio/*.

### 2.2 HubSpot — sink

What it does: for each matching `evaluation.completed`, find the HubSpot contact for the call and attach a **note** with the result.

Config: `match_by` (`phone` | `email` | `contact_id` from `metadata.crm_contact_id`), `only_failed` (default false), `note_template` (Jinja, default below), `public_base_url`. Secrets: `private_app_token`.

Flow:
1. If `metadata.crm_contact_id` → use it. Else search contacts by phone/email (CRM v3 search endpoint, filter on `phone`/`mobilephone` or `email`).
2. No match → delivery `skipped` (reason stored), not an error.
3. Create a note (CRM v3 notes object) with `hs_timestamp` and `hs_note_body`, associated to the contact.
4. Store the note id as `external_id` on the delivery.

Default note body:
```
Pareeksha call audit — FAIL (40/100) ⚠ critical
Agent: EMI Reminder Bot · Kannada · 1m 24s
Issues: asr_misrecognition, wrong_fact
Summary: Misheard 4,000 as 40,000 and confirmed it.
Details: https://pareeksha.example.com/calls/…
```

> Verify on Day 3 against HubSpot's current API docs: the exact search/notes endpoint paths, the note→contact association type, and the minimum private-app scopes. Build against a `respx` mock first so tests don't need a live portal; then test once with a free HubSpot developer account.

Rate limits: honour `429` + `Retry-After` via the retry topics. Idempotency: delivery row checked **before** creating the note.

### 2.3 Designed for (not built in v1)
| Connector | Direction | Notes for the implementer |
|---|---|---|
| Salesforce | sink | Task or custom object on Contact/Lead; OAuth (JWT bearer) |
| Zoho CRM | sink | Notes API; region-specific domains (`.in`) |
| LeadSquared | sink + source | Popular with Indian sales teams; activity post |
| Freshdesk | sink | Private note on ticket matched by `metadata.ticket_id` |
| Exotel | source | Poll Calls API or status-callback webhook → recording URL |
| Slack | sink | Message on critical failures with link |

A "write a connector" guide (DOC-02) walks through implementing one of these in one file plus tests.

---

## 3. SDK, CLI and config-as-code (`sdk/python/`, package `pareeksha-sdk`)

### 3.1 SDK
```python
from pareeksha_sdk import Pareeksha

pk = Pareeksha(base_url="http://localhost:8000", api_key="pk_live_…")
agent = pk.agents.get_by_name("EMI Reminder Bot")
run = pk.runs.create(agent_id=agent.id, scenario_tags=["happy_path"], persona_names=["Manju — auto driver"],
                     noise_profiles=["pstn_market_5db"], max_concurrency=3)
result = pk.runs.wait(run.id, timeout_s=1800)          # polls, or streams SSE
print(result.summary.pass_rate)

audit = pk.audits.create(file="call.wav", agent_id=agent.id, language="kn-IN")
```
Thin, typed (Pydantic models generated from the OpenAPI spec with `datamodel-code-generator`), sync + async clients, retries on 5xx.

### 3.2 CLI (`pareeksha`, Typer)
| Command | Does |
|---|---|
| `pareeksha login --url … --key …` | Saves profile to `~/.config/pareeksha/config.toml` |
| `pareeksha apply -f pareeksha.yaml` | Upserts agent, scenarios, personas, profiles by name |
| `pareeksha run --agent NAME [--tags …] --wait --fail-under 80` | Creates a run, streams progress, exit code 1 if pass rate/score below threshold |
| `pareeksha regress --agent NAME --wait` | Runs blocking regression tests; exit 1 on suite failure |
| `pareeksha audit FILE --agent NAME --language kn-IN` | Uploads a recording and prints the result |
| `pareeksha dlq list` / `pareeksha dlq replay ID` | Inspect and replay dead letters |
| `pareeksha doctor` | Checks API, database and Kafka connectivity and prints DLQ/outbox counts (speech/LLM provider probes are not exposed by the API) |

### 3.3 `pareeksha.yaml` (lives in the bot's own repo)
```yaml
version: 1
agent:
  name: EMI Reminder Bot
  adapter: pipecat            # audio_v1 | pipecat | livekit | vapi
  endpoint_url: wss://bot.example.com/ws
  languages: [kn-IN, hi-IN, en-IN]
  description: file://prompts/system_prompt.md
  mandatory_disclosures:
    - id: recording
      regex: "(record|ರೆಕಾರ್ಡ್|रिकॉर्ड)"
      within_turns: 2
scenarios:
  - title: Already paid, wants confirmation
    caller_goal: …
    success_criteria: …
    tags: [payment_dispute]
suites:
  pr_check:
    scenarios: {tags: [happy_path, payment_dispute]}
    personas: [Manju — auto driver, Ramesh ji — elderly]
    noise_profiles: [clean_16k, pstn_market_5db]
    fail_under: 80
```

## 4. Agent adapters (`pareeksha/adapters/`)

Every adapter exposes the same internal interface to the simulator: `connect(agent, call_ctx) → AudioSession` with `send_pcm16(frame)`, `async iter receive()` (audio frames + optional glass-box events) and `close()`.

| Adapter | How it connects | What the bot team does |
|---|---|---|
| `audio_v1` (Must) | Platform opens a WebSocket and speaks `pareeksha-audio-v1` (see `06-api-spec.md §7`) | Add a small WS endpoint (see [Guide 3](guides/03-connect-any-bot.md) for a minimal server; no helper library was built) |
| `pipecat` (Must) | Platform connects to the bot's existing Pipecat `FastAPIWebsocketTransport`; ships `PareekshaFrameSerializer` that maps protocol frames ↔ Pipecat frames, and emits glass-box events from Pipecat transcription/function-call frames | Add the serializer to their transport (≈5 lines) |
| `livekit` (Should) | Platform joins the bot's LiveKit room as a participant using a token from a URL the team provides; publishes caller track, subscribes to agent track | Expose a token endpoint for test rooms |
| `vapi` (Could) | Uses Vapi's WebSocket call transport to stream audio to/from an assistant | Provide assistant ID + API key (verify current Vapi transport docs on Day 4) |

Each adapter ships with a runnable example in `examples/` and a contract test against the mock agent.

## 5. GitHub Action (`action/`)

```yaml
# .github/workflows/voice-agent-tests.yml in the bot's repo
on:
  pull_request:
    paths: ["prompts/**", "pareeksha.yaml"]
jobs:
  pareeksha:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: <your-org>/pareeksha/action@v1
        with:
          api-url: ${{ secrets.PAREEKSHA_URL }}
          api-key: ${{ secrets.PAREEKSHA_KEY }}
          config: pareeksha.yaml
          suite: pr_check
```
Composite action: installs `pareeksha-sdk`, runs `pareeksha apply` then `pareeksha run --suite pr_check --wait`, writes a Markdown summary (pass rate, regressions, links) to `$GITHUB_STEP_SUMMARY`, exits 1 on failure.

## 6. One-command setup

```bash
git clone https://github.com/<you>/pareeksha && cd pareeksha
cp .env.example .env          # add GNANI_API_KEY, DEEPSEEK_API_KEY, SECRET_KEY, PAREEKSHA_API_KEY (see guide 1)
docker compose --profile workers up -d --build   # kafka, postgres, api, workers, web, mock-agent
docker compose run --rm api python -m pareeksha.seed   # personas, profiles, rubric, mock agent, demo key
open http://localhost:3000
```
The seed creates the admin API key from `PAREEKSHA_API_KEY` (or prints a generated one once); the web app and CLI use it. Target: from clone to seeing the first evaluated call in under 20 minutes (NFR-14).

## 7. Docs for adopters (DOC-02) — written, in `docs/guides/`
1. [Quick start (above)](guides/01-quickstart.md)
2. [Connect your Pipecat bot](guides/02-connect-pipecat.md)
3. [Connect any bot with `pareeksha-audio-v1`](guides/03-connect-any-bot.md)
4. [Send recordings in with the webhook source](guides/04-webhook-source.md)
5. [Send scores to HubSpot](guides/05-hubspot.md)
6. [Run tests on every PR with the GitHub Action](guides/06-github-action.md)
7. [Write your own connector (one file + entry point + tests)](guides/07-write-a-connector.md)
8. [Operating Kafka: topics, consumer lag, DLQ replay](guides/08-operating-kafka.md)
