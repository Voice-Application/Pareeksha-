# INT-03 proof: Generic Webhook source, import -> audit -> note through Kafka

Branch `task/INT-03`, created from `origin/integrate/M2b` (contains EVAL-04, EVAL-03b canonical evaluator, INT-01b, INT-02). Commit SHA: `git log -1 task/INT-03` (the commit contains this file).

## Built
- **`POST /webhooks/inbound/{integration_id}`** (`api/routers/webhooks.py`, replaces `STUB(INT-03)`; no API key): integration must exist, be enabled and be a registered connector with direction `source`/`both` (else `404`) -> HMAC verify over the raw body with `signing_secret` and, during rotation, `previous_signing_secret` (`401 invalid_signature`; timestamp older than 5 min `408 timestamp_out_of_window`) -> dedupe on `external_refs (integration_id, external_id)` (a repeat returns the first `call_id` with `duplicate: true`, no new call, no new event, no download) -> connector `ingest` (payload check, SSRF guard on `recording_url`: https only, no credentials, every resolved address public, `422 unsafe_url`) -> language check (`400`) -> agent by `agent_name` in the project, else the integration's `default_agent_id` (`422 unknown_agent`) -> in **one transaction**: `calls` row (`source=import`, `status=transcribing`, `metadata` = payload metadata for CRM matching), `external_refs` row (savepoint: a lost race on `external_id` resolves to the winner, `duplicate: true`), and `audit.requested` through the outbox. Returns `202 {call_id, duplicate}`.
- **`WebhookConnector`** is now `direction = "both"` and implements `ingest` (`integrations/webhook.py`); config gained optional `default_agent_id`. `signing.py`: `StaleTimestampError` (subclass of `SignatureError`) so the endpoint can answer 408.
- **Dev switch for import** (`integrations/ssrf.py: dev_allow_private()`): `PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1` now also covers the inbound URL check and the auditor's recording download (`audit/fetch.py`); off by default.
- The auditor/evaluator/integrations workers are unchanged: EVAL-04 already downloads imported URLs, stores them under `imports/<call_id>/`, and emits `call.completed`; EVAL-03b judges; INT-01b dispatches the sink.
- Contract notes in `CHANGELOG.md` (additive); `docs/06-api-spec.md` lists the extra error codes.

## Acceptance (docs/SCOPE.md INT-03; FR-IN-7, NFR-15)
| Criterion | Evidence |
|---|---|
| signed webhook with an import URL becomes a call and `audit.requested` | `tests/integration/test_inbound_webhook.py::test_signed_delivery_becomes_an_import_call_and_audit_requested` (real Postgres); real run below |
| bad signature rejected | test `..._bad_signature_is_401_and_creates_nothing`; real run: `401 invalid_signature` |
| stale/replayed rejected or deduped | test `..._stale_timestamp_is_408`, `..._same_external_id_twice_is_one_call`; real run: `408`, replay -> `202 duplicate: true` |
| unsafe URLs refused | parametrized test (http, loopback, private, link-local metadata IP, credentials in URL) -> `422 unsafe_url`, nothing created; real run: `422` |
| rotation, 404 for unknown/disabled/sink-only, unknown agent, default agent, bad language | tests in the same file (15 tests) |

## GOAL item 5: webhook-imported real recording -> audit -> note within 3 minutes
Command: `cd backend && PYTHONPATH=. python ../proof/INT-03/run_e2e.py ../proof/INT-03` (needs `GNANI_API_KEY`, `DEEPSEEK_API_KEY`; `DATABASE_URL`, `KAFKA_BOOTSTRAP_SERVERS` of a private stack: `docker compose -p pk-i03 ... up -d kafka kafka-init postgres` with ports 25432 / 29094). Output: `e2e_run.log`, `e2e_result.json` (full timeline, turns, evaluation, outbox, deliveries, usage), per-process logs in `logs/`.

Real, no mocks: Kafka + Postgres, the API (uvicorn) and the `outbox_relay`, `auditor`, `evaluator`, `integrations` consumers as separate processes, Gnani batch STT (diarize + denoise), DeepSeek (role check + judge), a local HTTPS receiver (self-signed, `PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1`) that serves the recording at the imported URL and receives the HMAC-signed sink delivery. The call is the two-speaker TTS clip from EVAL-04 (3 turns, 17.5 s).

Timestamps (UTC, 2026-10-27):
| Time | Step |
|---|---|
| 01:37:19.192 | signed `POST /webhooks/inbound` sent |
| 01:37:19.212 | `audit.requested` written to the outbox (same transaction as the call) |
| 01:37:19.215 | `202 {call_id: abf1edee-..., duplicate: false}` |
| 01:37:19.410 | auditor downloaded the recording from the import URL (558,764 bytes) |
| 01:37:38.8 | role check done, call completed (Gnani STT + DeepSeek) |
| 01:37:38.851 | evaluation row written (rubric-2026-10-v1, score 100.0, passed) |
| 01:37:43.775 | sink delivery claimed; 01:37:43.868 receiver got the signed POST (signature verified), HTTP 200 |

**Webhook -> sink delivery: 24.7 s** (limit 180 s). Turns: agent / caller / agent, matching the script. The sink payload carries `metadata.crm_contact_id`/`phone` from the webhook and the score, no transcript. Negative checks in the same run: wrong secret `401`, one-hour-old timestamp `408`, non-https URL `422 unsafe_url`; replay of the identical delivery `202 duplicate: true` (one `external_refs` row, one `audit.requested`).

## HubSpot: pending owner token
`HUBSPOT_ACCESS_TOKEN` is not set, so no live HubSpot call was made and **no note ID exists**. The note in this run is the signed webhook-sink delivery to the local receiver; the HubSpot sink (INT-02, built against `respx` mocks) is the same dispatch path, and its live step stays "pending owner token". To finish: create a `hubspot` integration with the token and the same inbound webhook; the contact is matched from `metadata.crm_contact_id` / phone / email.

## Reproduce tests
```
cd backend
python3 -m pytest tests -q --cov --cov-report=term      # 1039 passed, 0 failed, 0 skipped, coverage 96% (pytest_full.txt)
ruff check . && ruff format --check . && python3 -m mypy
```
Environment note: mypy needs `websockets>=16` (as the earlier proofs) and `types-PyYAML`; with websockets 15 two lines of `tests/unit/speech/test_deepgram.py` fail typing (unrelated to INT-03).

## Not done / issues
- The receiver in the real run is a local stand-in for the CRM; live HubSpot pending the owner's token (above).
- `agent_name` that matches no agent is `422 unknown_agent` unless `default_agent_id` is set on the integration (the spec did not say; chosen so an import never lands without a rubric).
