# Proof: TL-01 (freeze contracts as code)

Code commit: `f38fcfd` on branch `task/TL-01` (built on `claude/amazing-einstein-agkccc` @ `42fe878`, so EVAL-02 and INFRA-01 are included). Status: done-unverified (QA verifies).

## What was built (all under `backend/`)

| Contract | File |
|---|---|
| Kafka topics, keys, partitions, retention, retry/DLQ headers | `pareeksha/events/topics.py` |
| Envelope, 9 event payloads, `parse_envelope`, deterministic ids, JSON Schemas | `pareeksha/events/schemas.py` |
| Connector interface (ABC), summaries, `validate_connector_class` | `pareeksha/integrations/base.py` |
| `AudioSession`, `Adapter`, `pareeksha-audio-v1` messages | `pareeksha/adapters/base.py` |
| LLM provider interface and `LLM_PROVIDER` settings (owner-approved DeepSeek default) | `pareeksha/llm/base.py`, `pareeksha/llm/config.py` |
| API models | `pareeksha/schemas/*.py` |
| FastAPI app, 75 operations, error envelope, auth scheme, shared 501 helper | `pareeksha/api/main.py`, `errors.py`, `auth.py`, `stubs.py`, `deps.py`, `routers/*.py` |
| Tooling (ruff, mypy strict, pytest, coverage) | `pyproject.toml`, `requirements-dev.txt` |

Also: `docs/contracts.md` (approval summary), `docs/06-api-spec.md` section 12 (data-gap additions), `docs/schema.sql` (`api_usage.provider` allows `deepseek`), `.env.example` (LLM block), `CHANGELOG.md`, `NOTES.md`.

## Reproduce

```
pip install -r requirements.txt -r backend/requirements-dev.txt     # or: pip install fastapi pydantic-settings python-multipart psycopg psycopg-binary aiokafka pytest pytest-asyncio pytest-cov httpx ruff mypy
cd backend
python -m pytest -v --cov --cov-report=term      # expected: 455 passed (proof/TL-01/pytest.log)
ruff check .                                     # expected: All checks passed! (ruff.log)
python -m mypy                                   # expected: Success: no issues found in 61 source files (mypy.log)
python -m uvicorn pareeksha.api.main:app --port 8765   # then see live_server.txt
```

## Evidence in this folder

- `pytest.log`: 455 passed, 98% coverage on the measured modules (includes EVAL-02's 70+ tests, unchanged).
- `ruff.log`, `mypy.log`: clean.
- `openapi.json`: the full `/openapi.json` (75 operations, 58 paths).
- `live_server.txt`: real HTTP against a running uvicorn: openapi operation count, `501 not_implemented` with the owner task, `401` without a key, `400 validation_error` envelope, `503` health with no DB/Kafka.
- `stub_owners.txt`: every route grouped by the task that owns it.

## Tests added (backend/tests)

- `unit/test_event_schemas.py`: round trip and key for each of the 9 events, envelope bytes round trip, unknown field / missing field / bad value / cross-field rules per event, unknown type, naive timestamps, deterministic ids, JSON Schema export.
- `contract/test_topics_contract.py`: topics match the `03-TRD.md` 10.2 table and `create-topics.sh` (partitions, retention), retry-topic selection.
- `contract/test_openapi_routes.py`: `/openapi.json` contains every route of `docs/06-api-spec.md` (hand-enumerated list plus a parser that extracts every `METHOD /path` from the doc), no undeclared routes, status codes, security scopes, SSE/binary media types, multipart, pagination, 400-not-422.
- `contract/test_stub_routes.py`: every non-implemented route returns 501 with `details.owner` equal to the `# STUB(<id>)` marker in its source; owners exist in AGENTS section 7; no marker names TL-01; 401 without a key; validation envelope; `/runs/compare` not shadowed.
- `unit/test_adapter_interface.py`, `unit/test_connector_interface.py`, `unit/test_llm_provider_interface.py`: ABC enforcement, loopback implementations, protocol message parsing, connector validation, provider settings (env selection, defaults, cost).

## Tracked temporary stubs (R3), by owner task

73 route handlers return 501 through `pareeksha.api.stubs.not_implemented`: API-02 (31), API-04 (11), API-05 (9), EVAL-05 (8), API-03 (6), INT-01 (4), EVAL-04 (2), INT-03 (1), VOICE-04 (1). One more marker, `# STUB(API-01)`, is the API-key lookup and scope check inside `api/auth.py` (today it only rejects a missing bearer key). No `STUB(TL-01)` exists. Real, not stubbed: `GET /api/v1/health` and `/health` (INFRA-01 logic moved to `api/health.py`), `GET /api/v1/events/schemas`.

## Notes and caveats

- DeepSeek defaults come from api-docs.deepseek.com (checked 2026-10-23); see NOTES.md. No key was used; the providers themselves are EVAL-01.
- `backend/Dockerfile` pip line gained `python-multipart` and `pydantic-settings` (the app imports them).
- Three type-only edits in merged EVAL-02 code (`types.py`, `numbers.py`, `checks.py`) and one in `tests/evaluation/test_checks.py` so mypy passes; behaviour unchanged, the 70+ EVAL-02 tests still pass. EVAL-02 modules are checked but exempt from `disallow_untyped_defs` (override in `pyproject.toml`).
- When VOICE-02 merges, delete its `backend/pytest.ini` (pytest config is in `pyproject.toml`).
- INFRA-01's placeholder `api/main.py` (marked STUB(TL-01)) is replaced by this app; Compose still works because `/health` is served at the root.
