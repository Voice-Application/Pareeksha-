# API-02 proof

Branch `task/API-02` (from local `task/API-01`, commit 9ffd2f5). Commit SHA: see the report / `git log -1`.

## Built
- **31 handlers implemented, all `STUB(API-02)` markers removed** (a test greps the source for it):
  agents (create, list, get, patch, archive), scenarios (create, bulk, list, get, patch, delete),
  personas (create, list, get, patch, delete, preview), noise profiles (create, list, get, patch,
  delete, preview), integrations (create, list, get, patch, delete), api-keys (create, list, revoke).
  Routers: `backend/pareeksha/api/routers/{agents,scenarios,personas,noise_profiles,integrations,api_keys}.py`.
- Shared helpers: `api/crud.py` (opaque keyset cursor `created_at DESC, id DESC`, project-scoped
  lookups, Postgres constraint -> 409/400 mapping, Core `DELETE` so a referenced row is refused with
  409 instead of the ORM NULLing foreign keys), `api/deps.py` (`Db` = one transaction per request,
  committed before the response is sent), `api/auth.py` (`ReadKey/WriteKey/AdminKey` give handlers the
  authenticated `Principal`, so every query is scoped to the key's project), `api/speech.py`
  (persona preview TTS, injectable), `api/connectors.py` (connector name -> direction),
  `audio/preview.py` (WAV decode/encode, built-in sample, degrade through `LineSimulator`).
- Behaviour per spec: 201/200/204, 404 `not_found`, 409 `conflict` (duplicate name; delete of a
  scenario/persona/noise profile referenced by a run), 400 `validation_error` (bad body, unknown
  `agent_id`, unknown `background_category`, bad cursor), 403 scope, 413 `file_too_large` and 422
  `unsupported_audio` on the noise preview upload, 502 `upstream_error` on a TTS failure.
- **API keys**: `POST /api-keys` returns the full `pk_live_...` key once; only the SHA-256 is stored;
  list shows prefix/scopes/`last_used_at`/`revoked_at`, never the key; `DELETE` revokes (idempotent), a
  revoked key is 401 immediately.
- **Integrations**: secrets are write-only and Fernet-encrypted (`SECRET_KEY`) into
  `integrations.secrets_encrypted`; responses carry `secrets_set` only. `webhook` integrations get an
  `inbound_url` and a generated `signing_secret` returned once on creation and kept when other secrets
  are patched. A missing/invalid `SECRET_KEY` is a 500, never a leak.
- **Seed** (`python -m pareeksha.seed`, `backend/pareeksha/seed/`): project, 20 personas
  (8 kn-IN, 7 hi-IN, 5 en-IN; no two personas of a language share a voice), the **8 noise profiles
  loaded from `pareeksha.audio.profiles.BUILTIN_PROFILES`** (not a copy), rubric `rubric-2026-10-v1`
  (7 dimensions, weights sum to 100, anchors, active), the mock `EMI Reminder Bot` agent + 8 EMI
  scenarios, and an `admin` demo key (pin it with `PAREEKSHA_API_KEY`, otherwise it is generated and
  printed once). Every step is get-or-create on a natural key, so it is idempotent and never overwrites
  user edits.
- Housekeeping: `tests/db/conftest.py` moved to `tests/conftest.py` (shared fixtures `api`, `tenant`,
  `other_tenant`, `fresh_session_factory`); `tests/db/test_auth.py` and
  `tests/contract/test_stub_routes.py` updated (routes no longer 501; validation tests inject a dummy
  session factory); `pyproject.toml` gains `cryptography`, `numpy`, `scipy`, `pyyaml` (+ `types-PyYAML`),
  `fastapi>=0.121` (needed for `Depends(scope="function")`) and package-data for the seed YAML;
  `backend/Dockerfile` pip list gets the same runtime packages.

## Reproduce
```
docker compose up -d postgres
cd backend && pip install -e ".[dev]"
python -m pytest -q --cov=pareeksha -rs      # tests create/drop pareeksha_test_<hex> on the compose Postgres
ruff check . && ruff format --check . && python -m mypy
cd .. && ./proof/API-02/capture.sh           # scratch DB, seed x2, real uvicorn + curl, LIVE Gnani preview (needs GNANI_API_KEY)
```

## Results (real output)
- `pytest.txt`: full backend suite, 0 failed, 0 skipped (`-rs` lists none), coverage table, then
  `ruff check`, `ruff format --check`, `mypy` (strict) output.
- `seed_run1.txt` / `seed_run2.txt`: first run creates 20 personas / 8 profiles / 1 rubric / 1 agent /
  8 scenarios / 1 key; second run creates nothing.
- `api_walkthrough.txt`: against the real API on the seeded scratch DB: counts (20 / 8 / 1 / 8), 401
  without/with a bad key, create read-only key -> works -> 403 on write -> revoke -> 401, key list
  without keys, webhook integration (signing secret shown once, `secrets_set`, ciphertext prefix in the
  DB column).
- `previews.txt`, `noise_preview_pstn_market_5db.wav` (6.0 s, built-in sample through
  `pstn_market_5db`), `persona_preview_manju_kn.wav` (3.2 s, **live Gnani Timbre v3.0**, voice Prakash,
  kn-IN; one TTS call, about 40 characters).

## Not covered / notes
- Voices in `personas.yaml` were chosen by name/gender convention and **not auditioned by ear**
  (rubric section 8 asks for that); only the Kannada Prakash preview was generated and it was not
  listened to either. Dialect labels are descriptive flavour, not dialect claims.
- The noise-preview "built-in sample" is a synthetic voiced-burst signal (no real voice), so no
  recording ships with the repo; users can upload their own WAV (16-bit PCM, <= 10 MB, <= 60 s).
- `rubric_versions.prompt_hash` is the SHA-256 of the canonical rubric definition (version, threshold,
  dimensions) because `judge_v1.j2` does not exist yet; EVAL-03 should store its template hash in a
  new rubric version if it needs one.
- Seed data lives in `backend/pareeksha/seed/data/*.yaml` (not repo-root `data/seeds/`) because the
  compose build context is `./backend`.
- `webhook` is a `sink` here (matching INT-01's connector); the spec table in docs/10 says `both`.
- Connector directions come from `api/connectors.py` (entry points + the two shipped names) because
  the INT-01 registry is on another branch; after merge it should switch to
  `integrations.registry.get_registry()`. `integrations/crypto.py` is a byte-identical copy of INT-01's
  file so the merge is clean.
- `inbound_url` uses `PUBLIC_BASE_URL` (default `http://localhost:8000`); the real public API URL may
  differ from the web app URL.
- `POST /agents/{id}/test-connection` (VOICE-04), scenario generation (API-05), connector `test`/deliveries
  (INT-01) stay stubs owned by their tasks.
