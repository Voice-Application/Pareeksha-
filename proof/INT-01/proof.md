# INT-01 proof

Built (backend/pareeksha/integrations/): `registry.py` (entry-point discovery, contract validation, `GET /integrations/connectors` now real), `crypto.py` (Fernet SecretBox, `redact`), `signing.py` (HMAC v1, 5 min window, rotation with two secrets, constant-time), `ssrf.py` (https only, all resolved IPs public, IP pinned + SNI, no redirects, size/content-type limits), `webhook.py` (Generic Webhook sink: signed POST, only_failed/events filter, 5xx/429/timeout -> retryable, 4xx/SSRF -> permanent), `delivery.py` (claim row before `handle`; terminal rows are never re-sent; `DeliveryStore` protocol + in-memory store). Built-in registered under `[project.entry-points."pareeksha.connectors"]` in pyproject.

Reproduce (from backend/): `pip install -e .[dev]; python -m pytest -q --cov; python -m mypy; ruff check .; ruff format --check .`
Expected / actual (pytest.txt): 590 passed, 0 failed, 0 skipped; mypy strict clean; ruff clean; new modules 98-100% covered.

Acceptance mapping (SCOPE): entry-point discovery = test_registry_*; Fernet/never returned = test_fernet_*, secrets_set only; bad signature + stale timestamp = test_verify_rejects_*; SSRF private ranges = test_private_ranges_*, test_resolve_public_*; sink logs deliveries and idempotent per (integration, event) = test_sink_posts_*, test_delivery_is_idempotent_*.

Known gaps (not faked): the SQL `DeliveryStore` over `integration_deliveries`, the `integrations` Kafka consumer, and the integration CRUD/test/deliveries/redeliver routes (still STUB(INT-01) because they need the API-01 models/DB) are not built; the unit-level logic above is what they will call. Webhook is exercised against `httpx.MockTransport`, no live endpoint.
