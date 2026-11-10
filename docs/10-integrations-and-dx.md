# 10 — Integrations & Developer Experience · v0.2

Goal: another team can plug Pareeksha into **their** stack in under 30 minutes: run it, connect their bot, send it recordings, and get results back in their CRM or CI.

| Need | What ships | Status |
|---|---|---|
| Run it | `docker compose up` + `make demo` | Built |
| Connect a bot | Native `pareeksha-audio-v1` adapter + Pipecat adapter | Built |
| | LiveKit adapter | Not built (`livekit` is an accepted `adapter` value, but no adapter ships) |
| | Vapi adapter | Not built (same: accepted value, no adapter) |
| Drive it from code | `pareeksha-sdk` (Python, `sdk/python/`) + CLI | Built |
| Keep tests in their repo | `pareeksha.yaml` + `pareeksha apply` | Built |
| Gate releases | GitHub Action (`action/action.yml`) | Built |
| Send calls in | Generic Webhook **source** (signed) | Built |
| Send results out | Generic Webhook **sink** (signed) + **HubSpot** sink | Built |
| Other CRMs | Salesforce, Zoho CRM, LeadSquared, Freshdesk, Exotel source | Designed for, not built |
| Slack | Example sink connector in `examples/connector-slack/` (separate package, not a built-in) | Example only |

---

## 1. Connector framework (`pareeksha/integrations/`)

### 1.1 Interface (frozen contract)

```python
# backend/pareeksha/integrations/base.py (abridged)
from abc import ABC, abstractmethod
from typing import ClassVar, Literal
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

class Connector(ABC):
    name: ClassVar[str]                              # lowercase, no spaces: "hubspot"
    direction: ClassVar[Literal["source", "sink", "both"]]
    config_schema: ClassVar[type[BaseModel]]         # non-secret settings
    secrets_schema: ClassVar[type[BaseModel]]        # tokens etc. (encrypted at rest)
    subscribes_to: ClassVar[list[str]]               # sinks: event types, e.g. ["evaluation.completed"]

    @abstractmethod
    async def test(self, config, secrets) -> TestResult: ...   # mandatory
    # sink: react to a platform event (must be idempotent; framework records the delivery).
    # The base class raises ConnectorDirectionError, so a sink only overrides handle.
    async def handle(self, event: "AnyEnvelope", config, secrets, ctx: "DeliveryCtx") -> "DeliveryOutcome": ...
    # source: turn an inbound webhook into audit requests (signature already verified)
    async def ingest(self, request: InboundRequest, config, secrets) -> list[AuditRequest]: ...
```

`DeliveryOutcome` is `{ status: succeeded | failed | skipped, http_status, external_id, response_excerpt, detail }`. `DeliveryCtx` carries `integration_id`, `delivery_id`, `attempt`, `public_base_url` and, for `evaluation.completed`, the `EvaluationSummary` (§1.4). Raise `ConnectorRetryableError` (timeouts, 5xx, 429; optional `retry_after_s`) to retry through the retry topics, or `ConnectorPermanentError` (bad config, auth failure, 4xx) to record a failed delivery without retrying. `validate_connector_class` checks every entry point (abstract methods, name, direction, schemas) and the registry refuses classes that fail.

### 1.2 Registration
Connectors are discovered via the entry-point group **`pareeksha.connectors`**:

```toml
# pyproject.toml of a third-party package, e.g. pareeksha-connector-zoho
[project.entry-points."pareeksha.connectors"]
zoho = "pareeksha_connector_zoho:ZohoConnector"
```
`pip install pareeksha-connector-zoho` + restart = the connector appears in `GET /integrations/connectors` and the web app's "Add integration" list. The two built-ins (`webhook`, `hubspot`) register the same way, in `backend/pyproject.toml`.

### 1.3 What the framework does for every connector
- Validates `config` / `secrets` with the connector's schemas; encrypts secrets (Fernet, `SECRET_KEY`).
- **Sinks:** the `integrations` consumer reads `evaluation.completed` and `run.completed`, finds enabled sink integrations whose `event_filter` matches (event type, agent IDs, `only_failed`, `min_score_below`), inserts an `integration_deliveries` row (`UNIQUE (integration, event, outbound)` → no double posting), calls `handle`, records status/HTTP code/external id. Retryable failures (timeouts, 5xx, 429 with `Retry-After`) go through the standard retry topics; after 3 attempts → DLQ.
- **Sources:** `POST /webhooks/inbound/{integration_id}` → verify → `ingest` → dedupe on `external_refs` → create `calls` row (`source=import`, `metadata`) + `audit.requested` via outbox, all in one transaction.
- `POST /integrations/{id}/test` → `test()`; result stored in `last_test_ok`.
- Delivery log (`GET /integrations/{id}/deliveries`, paginated; status, HTTP status, external id, response excerpt) and `POST /integrations/{id}/deliveries/{delivery_id}/redeliver`.

### 1.4 Data minimisation
Sinks receive an `EvaluationSummary` (call id, agent, scenario/persona if simulated, score, passed, critical, failure types, judge summary, top 3 failing dimension reasons, deep link, `call.metadata`). **No transcript or audio**: the summary schema has no field for them and no connector offers an `include_transcript` option.

---

## 2. v1 connectors

### 2.1 Generic Webhook — source + sink

**Signing (both directions, Stripe-style):**
```
X-Pareeksha-Timestamp: 1761478500
X-Pareeksha-Signature: v1=<hex(hmac_sha256(secret, f"{timestamp}.{raw_body}"))>
```
Receivers reject timestamps outside a 5-minute window and compare with constant-time equality. Secret rotation: set `previous_signing_secret` and both signatures are sent (`v1=...,v1=...`). Outbound posts also carry `X-Pareeksha-Event-Id` (stable across retries and redeliveries; dedupe on it).

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
Config: `url` (https only), `events` (default `["evaluation.completed"]`), `only_failed`, `timeout_s` (default 10, max 60), `default_agent_id` (source side: the agent used when `agent_name` matches none). Secrets: `signing_secret` (at least 16 characters), optional `previous_signing_secret`. `data` is the `EvaluationSummary` (with `agent_id`/`agent_name` folded into `agent`), so it also carries `scenario`, `persona`, `language`, `duration_ms` and `top_failing_dimensions`; for `run.completed` it is the event payload.

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
→ `202 {"call_id": "…", "duplicate": false}`. Recording URL guard: https only, DNS-resolved IP must not be private/loopback/link-local, max 10 MB, content-type `audio/*` or an untyped byte stream (`application/octet-stream`); redirects are not followed.

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
Pareeksha call audit - FAIL (40/100) CRITICAL
Agent: EMI Reminder Bot - kn-IN - 1m 24s
Issues: asr_misrecognition, wrong_fact
Summary: Misheard 4,000 as 40,000 and confirmed it.
Details: https://pareeksha.example.com/calls/…
```

Idempotency has two layers: the delivery row is inserted before the note is created, and the connector also looks for an existing note on the contact containing a marker derived from the event id, so a replayed event does not post twice.

Rate limits: `429` + `Retry-After` and 5xx are retried via the retry topics.

### 2.3 Designed for (not built)
| Connector | Direction | Notes for the implementer |
|---|---|---|
| Salesforce | sink | Task or custom object on Contact/Lead; OAuth (JWT bearer) |
| Zoho CRM | sink | Notes API; region-specific domains (`.in`) |
| LeadSquared | sink + source | Popular with Indian sales teams; activity post |
| Freshdesk | sink | Private note on ticket matched by `metadata.ticket_id` |
| Exotel | source | Poll Calls API or status-callback webhook → recording URL |

`examples/connector-slack/` is a working one-file sink (Slack incoming webhook for failed calls) packaged as a third-party connector; the [write-a-connector guide](guides/07-write-a-connector.md) walks through it.

---

## 3. SDK, CLI and config-as-code (`sdk/python/`, package `pareeksha-sdk`)

### 3.1 SDK
```python
from pareeksha_sdk import Pareeksha

pk = Pareeksha(base_url="http://localhost:8000", api_key="pk_live_…")
agent = pk.agents.get_by_name("EMI Reminder Bot")
scenario = pk.scenarios.get_by_name("Already paid, wants confirmation")
persona = pk.personas.get_by_name("Manju — auto driver")
noise = pk.noise_profiles.get_by_name("pstn_market_5db")
run = pk.runs.create(agent.id, [scenario.id], [persona.id], [noise.id], max_concurrency=3)
result = pk.runs.wait(run.id, timeout_s=1800)          # polls GET /runs/{id}
print(result.summary.pass_rate)

ref = pk.audits.create("call.wav", agent.id, "kn-IN")
call = pk.audits.wait(ref.call_id)
```
Thin and typed (hand-written Pydantic response models that keep unknown fields, so a newer server does not break an older SDK). `Pareeksha` (sync) and `AsyncPareeksha` (async) share the core of agents, scenarios, personas, noise profiles, runs (`create`, `create_regression`, `get`, `items`, `cancel`, `wait`), audits, DLQ (`list`, `replay`, `discard`) and `report_tool_calls`; only the sync client also has `kb`, `rag` (RAG matrices, reports, pricing), prompt versions, designer, LLM settings, `health` and `metrics_summary`. Gateway errors, and 5xx on idempotent calls, are retried up to `max_retries` (default 3); `timeout_s` defaults to 30. See [sdk-reference](guides/sdk-reference.md).

### 3.2 CLI (`pareeksha`, Typer)
| Command | Does |
|---|---|
| `pareeksha login --url … --key …` | Saves profile to `~/.config/pareeksha/config.toml` |
| `pareeksha apply -f pareeksha.yaml` | Upserts agent, scenarios, personas, profiles by name |
| `pareeksha run [--agent NAME] [--tags a,b] [--suite NAME] [--persona NAME]… [--noise NAME]… [-f FILE] [--wait] [--fail-under PCT] [--timeout S] [--summary-file F]` | Creates a run from a suite or ad-hoc selection; with `--wait` (implied by `--fail-under`) streams progress by polling and exits 1 when the pass rate is below the threshold, 2 on errors |
| `pareeksha regress --agent NAME [--wait/--no-wait]` | Runs blocking regression tests; exit 1 on suite failure |
| `pareeksha audit FILE --agent NAME --language kn-IN` | Uploads a recording, waits, prints the call JSON |
| `pareeksha dlq list [--status open]` / `pareeksha dlq replay ID` | Inspect and replay dead letters (discard is SDK/API only) |
| `pareeksha prompt push \| versions \| activate \| set-key` | Prompt-agent versions and the write-only agent LLM key |
| `pareeksha kb create \| set-keys \| upload \| index`, `pareeksha kb questions generate \| import` | Knowledge bases for RAG testing |
| `pareeksha rag run \| report \| pricing` | RAG matrices, reports and prices |

Credentials come from `PAREEKSHA_URL` / `PAREEKSHA_KEY` or the profile saved by `login`. There is no `doctor` command; use `GET /health` and `GET /metrics/summary`.

### 3.3 `pareeksha.yaml` (lives in the bot's own repo)
```yaml
version: 1
agent:
  name: EMI Reminder Bot
  adapter: pipecat            # audio_v1 | pipecat (livekit and vapi are accepted values but not built)
  endpoint_url: wss://bot.example.com/ws
  languages: [kn-IN, hi-IN, en-IN]
  description: file://prompts/system_prompt.md
  mandatory_disclosures:
    - id: recording
      text: This call is being recorded for quality purposes   # required
      regex: "(record|ರೆಕಾರ್ಡ್|रिकॉर्ड)"
      within_turns: 2
scenarios:
  - title: Already paid, wants confirmation
    caller_goal: …
    success_criteria: …
    tags: [payment_dispute]
suites:
  pr_check:
    scenarios: {tags: [happy_path, payment_dispute]}   # or titles: [...]
    personas: [Manju — auto driver, Ramesh ji — elderly]
    noise_profiles: [clean_16k, pstn_market_5db]
    fail_under: 80            # minimum pass rate, percent
    repeats: 1                # optional; max_concurrency is optional too
```

## 4. Agent adapters (`pareeksha/adapters/`)

Every adapter exposes the same internal interface to the simulator: `connect(agent, call_ctx) → AudioSession` with `send_pcm16(frame)`, `async iter receive()` (audio frames + optional glass-box events) and `close()`.

| Adapter | How it connects | What the bot team does |
|---|---|---|
| `audio_v1` | Platform opens a WebSocket and speaks `pareeksha-audio-v1` (see `06-api-spec.md §7`) | Add a small WS endpoint (see [Guide 3](guides/03-connect-any-bot.md) for a minimal server; no helper library was built) |
| `pipecat` | Platform connects to the bot's existing Pipecat `FastAPIWebsocketTransport`; ships `PareekshaFrameSerializer` that maps protocol frames ↔ Pipecat frames, and emits glass-box events from Pipecat transcription/function-call frames | Add the serializer to their transport (≈5 lines) |
| `livekit` | **Not built.** Accepted as an `adapter` value, but `adapters/registry.py` has no implementation, so calls to such an agent fail with an "adapter not available" error | n/a |
| `vapi` | **Not built.** Same as `livekit` | n/a |
| `prompt` | No audio transport: the simulator runs the agent's active prompt version (system prompt, tools, mock tool results) against an LLM; see [Guide 9](guides/09-prompt-testing.md) | Create prompt versions via `/agents/{id}/prompt-versions` |

The registry (`adapters/registry.py`) lists only `audio_v1` and `pipecat`. The runnable bot example is `examples/pipecat-bot/`; `mock_agent/` is the reference `audio_v1` server.

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
Composite action (Python 3.12): installs `sdk-package` (default `pareeksha-sdk`), runs `pareeksha apply -f <config>` then `pareeksha run --suite <suite> -f <config> --wait --timeout <timeout>` (the CLI appends a Markdown summary to `$GITHUB_STEP_SUMMARY`), and exits 1 when the pass rate is below the threshold. Inputs: `api-url` and `api-key` (needs `read` and `runs:write`) and `suite` are required; `config` (default `pareeksha.yaml`), `fail-under` (percent; overrides the suite's `fail_under`), `timeout` (default 1800), `regression` (`"true"` also runs `pareeksha regress` for the blocking regression suite), `sdk-package`, `web-url` (links in the summary) are optional. The mock-agent CI example is `examples/ci/pareeksha.yaml`.

## 6. One-command setup

```bash
git clone https://github.com/<you>/pareeksha && cd pareeksha
cp .env.example .env          # add GNANI_API_KEY, DEEPSEEK_API_KEY, SECRET_KEY, PAREEKSHA_API_KEY, SESSION_SECRET (16+ chars; see guide 1)
docker compose --profile workers up -d --build   # kafka, postgres, api, workers, web, mock-agent
docker compose run --rm api python -m pareeksha.seed   # personas, profiles, rubric, mock agent, demo key
open http://localhost:3000
```
`make demo` (`scripts/demo.sh`) does the same end to end and generates `SECRET_KEY`, `PAREEKSHA_API_KEY` and `SESSION_SECRET` in `.env` when they are empty. The seed creates the admin API key from `PAREEKSHA_API_KEY` (or prints a generated one once); the web server and CLI use it. The web app has its own sign-in: the first visit creates the first admin account (`POST /auth/bootstrap`), who can then add `admin` and `member` users. Target: from clone to seeing the first evaluated call in under 20 minutes (NFR-14).

## 7. Docs for adopters, in `docs/guides/`
1. [Quick start (above)](guides/01-quickstart.md)
2. [Connect your Pipecat bot](guides/02-connect-pipecat.md)
3. [Connect any bot with `pareeksha-audio-v1`](guides/03-connect-any-bot.md)
4. [Send recordings in with the webhook source](guides/04-webhook-source.md)
5. [Send scores to HubSpot](guides/05-hubspot.md)
6. [Run tests on every PR with the GitHub Action](guides/06-github-action.md)
7. [Write your own connector (one file + entry point + tests)](guides/07-write-a-connector.md)
8. [Operating Kafka: topics, consumer lag, DLQ replay](guides/08-operating-kafka.md)
9. [Test a prompt without a voice endpoint](guides/09-prompt-testing.md)
10. [Test RAG: knowledge bases, indexes and matrices](guides/10-rag-testing.md)

The Python SDK and CLI are documented in [sdk-reference](guides/sdk-reference.md).
