# Guide 5 · Send scores to HubSpot

Goal: for every judged call, attach a note with the result to the matching HubSpot contact.

**Prerequisite:** the stack from [Guide 1](01-quickstart.md); a HubSpot account and a **private app** token.

## 1. Create the HubSpot private app

HubSpot, Settings, Integrations, Private Apps, Create. Scopes: `crm.objects.contacts.read`, `crm.objects.contacts.write`. Copy the access token (starts with `pat-`).

## 2. Add the integration

```bash
API=http://localhost:${API_HOST_PORT:-8000}/api/v1
curl -s -X POST "$API/integrations" -H "Authorization: Bearer $PAREEKSHA_API_KEY" -H "Content-Type: application/json" -d '{
  "connector": "hubspot",
  "name": "HubSpot collections portal",
  "config": {"match_by": "phone", "only_failed": false, "public_base_url": "http://localhost:3000"},
  "secrets": {"private_app_token": "pat-..."},
  "event_filter": {"events": ["evaluation.completed"]}
}'
```

`match_by` is `phone`, `email` or `contact_id`. A call is matched through its `metadata`: `crm_contact_id` wins if present, else `phone` / `email` (the metadata of an imported call, [Guide 4](04-webhook-source.md)). `only_failed: true` posts failures only. The token is encrypted at rest (Fernet, `SECRET_KEY`) and never returned.

Test it (authenticates against HubSpot, no side effects):

```bash
curl -s -X POST "$API/integrations/<id>/test" -H "Authorization: Bearer $PAREEKSHA_API_KEY"
# {"ok":true,"detail":"HubSpot token accepted"}
```

The same form exists in the web app under Integrations.

## 3. What it posts

For each matching `evaluation.completed` the connector finds the contact (CRM v3 search by `phone`/`mobilephone` or `email`), then creates a **note** (`POST /crm/v3/objects/notes`) associated with the contact (association type 202, note to contact). No match is recorded as a `skipped` delivery with the reason, not an error. The note body is rendered from a sandboxed Jinja template (`note_template`; variables `verdict`, `score`, `critical`, `agent`, `language`, `duration`, `issues`, `summary`, `link`) and ends with a `[pareeksha event <id>]` marker. The default:

```
Pareeksha call audit - FAIL (40/100) CRITICAL
Agent: EMI Reminder Bot - kn-IN - 1m 24s
Issues: asr_misrecognition, wrong_fact
Summary: Misheard 4,000 as 40,000 and confirmed it.
Details: <public_base_url>/calls/<id>
```

It is idempotent: the delivery row for (integration, event, direction) is claimed before the connector runs, so a redelivered event returns the stored note id without calling HubSpot; after a crash the connector also looks for a note on the contact that already carries the event marker. A HubSpot `401`/`403` is a permanent failure (bad token or missing scopes). HubSpot `429` honours `Retry-After` through the retry topics; after 3 attempts the event lands in the DLQ.

## 4. See the deliveries

```bash
curl -s "$API/integrations/<id>/deliveries" -H "Authorization: Bearer $PAREEKSHA_API_KEY" | python3 -m json.tool
```

Each row has `direction`, `status` (`pending`, `succeeded`, `failed`, `skipped`), `http_status`, `external_id` (the HubSpot note id) and the number of attempts.

## 5. End-to-end check

1. Create a HubSpot contact with a phone number such as `+919800000001`.
2. Send an audit for that number: `pareeksha audit call.wav --agent "EMI Reminder Bot" --language kn-IN` does not carry CRM metadata, so import it through the signed webhook with `"metadata": {"phone": "+919800000001"}` ([Guide 4](04-webhook-source.md)).
3. When the call is judged, the contact's activity feed shows the note.

## Notes and limits

- The HubSpot code is covered by mocked-API tests: `docker compose run --rm --no-deps -v "$PWD/backend/tests:/app/tests:ro" api sh -c "pip install -q pytest pytest-asyncio respx && python -m pytest tests/unit/integrations/test_hubspot_sink.py -q"`; exercise it once against a free HubSpot developer account before you rely on it.
- Only `evaluation.completed` is subscribed. Transcripts are never sent.
- Other CRMs (Salesforce, Zoho, LeadSquared, Freshdesk, Slack) are designed for but not built: see [Guide 7](07-write-a-connector.md).
