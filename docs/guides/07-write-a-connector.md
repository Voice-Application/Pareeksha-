# Guide 7 · Write your own connector

Goal: add a new source or sink (Salesforce, Zoho CRM, LeadSquared, Freshdesk, Slack, Exotel...) as a separate Python package: **one file, one entry point, a few tests**. Pareeksha discovers it at start-up; it then appears in `GET /integrations/connectors` and in the web app's "Add integration" list with a form generated from your schemas.

A finished example lives in `examples/connector-slack/` (a Slack sink that alerts on critical failures). This guide builds it step by step.

## 1. The contract

Subclass `pareeksha.integrations.base.Connector`:

| Member | Meaning |
|---|---|
| `name` | lowercase, no spaces (`"slack"`) |
| `direction` | `"source"`, `"sink"` or `"both"` |
| `config_schema` / `secrets_schema` | Pydantic models: non-secret settings / tokens (encrypted at rest, write-only through the API) |
| `subscribes_to` | sinks: event types, e.g. `["evaluation.completed"]` |
| `async test(config, secrets) -> TestResult` | credential/reachability check, no side effects (`POST /integrations/{id}/test`) |
| `async handle(event, config, secrets, ctx) -> DeliveryOutcome` | sink: react to an event. `ctx.summary` is an `EvaluationSummary` (score, passed, critical, failure types, judge summary, top failing dimensions, deep `link`, `metadata`; never a transcript) |
| `async ingest(request, config, secrets) -> list[AuditRequest]` | source: turn a verified inbound webhook into audit requests |

The framework does the rest: validates config/secrets, encrypts secrets, writes the delivery row **before** calling `handle` (so a replayed event cannot post twice), retries `ConnectorRetryableError` (timeouts, 5xx, 429 with `Retry-After`) and sends it to the DLQ after 3 attempts, and records `ConnectorPermanentError` (bad config, 4xx) as a failed delivery. Return `DeliveryOutcome(status="skipped", detail=...)` for "nothing to do" (for example no matching contact).

## 2. The file

`examples/connector-slack/pareeksha_connector_slack.py` is the whole connector (about 70 lines): the two schemas, `SlackConnector.test`, and `SlackConnector.handle`, which skips passing calls, builds a message from the summary and POSTs it with `httpx`, mapping 429/5xx to `ConnectorRetryableError` and other 4xx to `ConnectorPermanentError`. Copy it as a template.

## 3. The entry point

```toml
# pyproject.toml of your package
[project.entry-points."pareeksha.connectors"]
slack = "pareeksha_connector_slack:SlackConnector"
```

Built-in connectors (`webhook`, `hubspot`) register the same way. A class that breaks the contract is refused and listed under `rejected` instead of stopping start-up.

## 4. Tests

`examples/connector-slack/tests/test_slack.py` checks the contract with `validate_connector_class` and drives `handle` with `httpx.MockTransport`, so no real Slack is needed. Inject the transport through `__init__` in your own connector for the same reason. Run them (the `pareeksha` package must be importable, which it is inside the backend image):

```bash
docker compose run --rm --no-deps -v "$PWD/examples/connector-slack:/ext-src" api \
  sh -c "pip install -q pytest && cp -r /ext-src /tmp/ext && cd /tmp/ext && python -m pytest -q tests"
```

## 5. Install it into the stack

The `api` (for the connector list and `/test`) and `integrations` (for deliveries) containers both need the package. The overlay `examples/connector-slack/docker-compose.connector.yml` installs it at start-up:

```bash
docker compose -f docker-compose.yml -f examples/connector-slack/docker-compose.connector.yml --profile workers up -d api integrations
curl -s -H "Authorization: Bearer $PAREEKSHA_API_KEY" http://localhost:${API_HOST_PORT:-8000}/api/v1/integrations/connectors | python3 -c "import sys,json; print([c['name'] for c in json.load(sys.stdin)])"
# ['hubspot', 'slack', 'webhook']
```

For a real deployment, publish your package and add `pip install pareeksha-connector-slack` to a small Dockerfile based on the backend image instead of the start-up install.

## 6. Use it

```bash
curl -s -X POST http://localhost:${API_HOST_PORT:-8000}/api/v1/integrations -H "Authorization: Bearer $PAREEKSHA_API_KEY" -H "Content-Type: application/json" -d '{
  "connector":"slack","name":"Collections alerts",
  "config":{"only_critical":true},
  "secrets":{"webhook_url":"https://hooks.slack.com/services/T000/B000/XXXX"},
  "event_filter":{"events":["evaluation.completed"]}}'
```

## Source connectors

Implement `ingest` (and `direction = "source"` or `"both"`). The framework exposes `POST /webhooks/inbound/{integration_id}`, verifies the HMAC signature with your secrets' `signing_secret`, calls `ingest`, dedupes on `external_id`, and creates the call and its audit. Return one `AuditRequest(recording_url, language, external_id, agent_name?, metadata)` per recording; the SSRF-safe fetch (https, public IPs, 10 MB, `audio/*`) is applied for you. See `backend/pareeksha/integrations/webhook.py` for a complete source.
