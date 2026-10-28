# INT-02 proof: HubSpot sink

Built: `backend/pareeksha/integrations/hubspot.py` (HubSpotConnector, entry point `hubspot`), tests in
`backend/tests/unit/integrations/test_hubspot_sink.py`; `jinja2` added to dependencies.

Behaviour: contact by `metadata.crm_contact_id`, else search by phone (phone/mobilephone, as given and +digits) or email;
no match -> `skipped`; one note associated to the contact (type 202); note id stored as delivery `external_id`;
401/403 -> permanent error naming the token/scopes; 429/5xx/timeouts -> retryable (Retry-After honoured).
Idempotency (GOAL item 6): two layers. (a) the delivery row is claimed before `handle`, so replays make no HTTP call. (b) crash-safe: every note carries the marker `[pareeksha event <event_id>]`; before creating, the contact's associated notes (v4 associations list, paginated, then notes batch read) are scanned for it and the existing note id is returned. Tests: replay x4 gives 1 note; worker crash after create but before row save, then retry, still gives 1 note; marker found across association pages with a fresh store. The association-list endpoint shapes are mock-verified only until the live token run.
tests show 4 deliveries of one event produce exactly 1 search and 1 note, and a 503 then retry still gives 1 note.

Reproduce: `cd backend && pip install -e .[dev] && python -m pytest -q --cov && ruff check . && ruff format --check . && python -m mypy --strict pareeksha`
Expected: 611 passed, 0 failed, 0 skipped; total coverage 98% (hubspot.py 99%); ruff and mypy clean.

## Live HubSpot: PENDING
Real HubSpot note ID + screenshot: pending owner token (HUBSPOT_ACCESS_TOKEN not available). No note ID has been produced
or faked; all HTTP in the tests is mocked. Live check once the token exists: create a developer-account contact with a
synthetic phone, deliver one `evaluation.completed` twice, confirm one note on the contact, screenshot it.
