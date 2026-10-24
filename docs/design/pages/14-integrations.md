# 14. Integrations (+ delivery log)  `/integrations`, `/integrations/[id]`

Requirements: FR-IN-1..10 (Must; delivery log and redeliver Should), FR-DX-10 docs. v1 connectors: Generic Webhook (source and sink, HMAC) and HubSpot sink; others are designed for, not built. Purpose: connect Pareeksha to the tools the team already uses, prove the connection works, and see exactly what was sent.

## List `/integrations`

```
EYEBROW  2 connected
TITLE    Integrations                                               [Add integration]
+-- DataTable -----------------------------------------------------------------------+
| Name                      Connector  Direction  Events               Last delivery  Health     |
| HubSpot, collections      hubspot    sink       evaluation.completed 2 min ago      ok         |
| Exotel webhook            webhook    both       evaluation.completed 1 h ago        1 failed   |
+-----------------------------------------------------------------------------------+
+-- Panel: Available connectors (compact rows) ------------------------------------------+
| hubspot (sink)  webhook (source + sink)   Salesforce, Zoho, LeadSquared, Freshdesk, Exotel, Slack: "Planned"  |
+----------------------------------------------------------------------------------+
```
- Health cell: last test result and delivery health: `ok` (check), `N failed` (cross + count, links to log with failed filter), `untested` (neutral dash).
- Planned connectors are listed as plain text with a neutral "Planned" chip and no action, so no one thinks they exist (SCOPE: designed for only).

## Add integration (Sheet 520px)
1. Choose connector: list from `GET /integrations/connectors` (name, direction, one-line description).
2. **Form** rendered by `JsonSchemaForm` from `config_schema` and `secrets_schema`, plus fixed fields: name, `EventFilter` (events multiselect, agents multiselect, "only failed" switch, "score below" number). Secret inputs are `SecretField` (write-only). HubSpot: match-by segmented (`crm_contact_id`, `phone`, `email`), `public_base_url`, token (secret).
3. Footer: `Save` and `Save and test`. After saving a Generic Webhook the Sheet shows a one-time reveal: inbound URL (`CopyField`) and the generated signing secret (`CopyField` with "Shown once. Store it now" and a required "I copied it" checkbox before Close is enabled).

## Detail `/integrations/[id]`
Tabs (`SegmentedControl` in the page header): `Settings`, `Deliveries`, `Docs`.

**Settings:** same form as above prefilled; secrets show "Set" with `Replace`; `Test connection` panel on the right (result strip: ok with detail, e.g. "Authenticated as portal 12345678"; or failure with reason); `Delete` in a danger section (ConfirmDialog naming the integration; explains deliveries are kept for audit).

**Deliveries (the delivery log):**
```
[Status v: all|succeeded|failed|skipped] [Direction v] [Date v]
Time        Event                      Direction  Status     HTTP  External id  Attempts  
2 min ago   evaluation.completed #a1f  outbound   succeeded  201   note-555     1         [view]
1 h ago     evaluation.completed #9c2  outbound   failed     429   -            3         [Redeliver] [view]
```
Row `view` opens a Sheet: request summary (event id, payload digest, no transcript by default), response status and excerpt (first 500 chars, mono, truncated with disclosure), timestamps per attempt, `Redeliver` button (ConfirmDialog: "Idempotent. If it already succeeded, nothing is sent twice"). Inbound deliveries (Generic Webhook source) show `external_id`, duplicate flag, and the created call link. Failed rows use `--fail-fg` icon plus the word; skipped rows are neutral with the reason ("no matching contact").

**Docs tab:** static, per-connector instructions rendered from the connector schema plus the signature algorithm snippet for webhooks (`X-Pareeksha-Timestamp`, `X-Pareeksha-Signature: v1=...`) in a mono block with copy.

## Components
`PageHeader`, `DataTable`, `Sheet`, `JsonSchemaForm`, `SecretField`, `CopyField`, `EventFilter`, `SegmentedControl`, `StatusPill`, `ConfirmDialog`, `Button`, `CodeBlock`.

## Data
`GET /integrations/connectors`, `GET/POST/PATCH/DELETE /integrations`, `POST /integrations/{id}/test`, `GET /integrations/{id}/deliveries?status=`, `POST /integrations/{id}/deliveries/{delivery_id}/redeliver`. Secrets are never returned (`secrets_set: true`).

## States
- **Empty:** "No integrations yet. Send scores to HubSpot or any webhook, or import calls from your telephony tool." Primary `Add integration`; secondary link to the guides.
- **No deliveries yet (Deliveries tab):** "Nothing has been delivered. Events matching this filter will appear here." with a `Send test event` button if the API supports it, else only text.
- **Filtered empty:** standard.
- **Loading:** skeleton rows; Sheet form shows field skeletons while the connector schema loads.
- **Error:** schema load failure blocks the form with Retry (the form is useless without it); save validation errors map to fields from the API's JSON pointer; test failures are specific results, not errors (a bad token is `ok: false` and shown as a fail strip with the reason); delivery list error standard.
- **Partial:** one failing connector does not affect others; list shows `1 failed` only for that row.
- **Redeliver result:** Toast "Redelivery queued" then the row updates; a second click while queued is disabled.
- **Security:** no secret value is ever rendered or kept in React state after save; copy-once fields clear on Sheet close; the signing secret cannot be retrieved later (copy: "Create a new secret to rotate" with a `Rotate secret` action if the API supports it).
