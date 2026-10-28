# QA-04 proof: Playwright smoke with real data, contract tests, bundle scan (STATUS: done-unverified)

Branch `task/QA-04` (from `task/FIX-01`). Stack: private compose project `pk-f1` (API :38000), seeded, with the real runs from FIX-01
(`bug2-no_amount_confirm`, `clean-a`: real Gnani + DeepSeek). Web served by `next start -p 3200` against that API.

## What was added
- `web/playwright.real.config.ts`, `web/tests/real/*.spec.ts` (npm `test:real`): no mocks, no fake upstream.
  - `smoke.spec.ts` (FR-DB-1): every sidebar page returns 200, shows the layout and an h1, shows real seeded text on Agents/Scenarios/Personas/Noise profiles, has no console errors or 5xx responses; plus run detail and call detail of a real evaluated call. 17 screenshots in `screenshots/`.
  - `run_detail.spec.ts` (FR-DB-2 static half), `call_detail.spec.ts` (FR-DB-3: evidence/turn click seeks the real recording), `dialect.spec.ts` (FR-DB-4: renders; the stack has no ASR report so this is the empty state only, the heatmap/drill-down are NOT covered here), `integrations.spec.ts`, `bundle_scan.spec.ts` (FR-DB-5: the API key is in no `.next/static` file, no page HTML and no response the browser receives, on all 15 pages).
  - The existing mock-based specs are excluded from this config; the default config ignores `tests/real/`.
- `backend/tests/contract/test_schema_dts_fresh.py` (FR-DB-6), `test_event_schemas.py` (event schemas: every event type has a payload/topic/key/valid JSON Schema, the route returns the module schemas, documented in `docs/contracts.md`, envelope rejects unknown fields), `test_secret_scan_and_logs.py` (NFR-8: no credentials in tracked files, `.env` untracked, bearer key not logged; regex scan, gitleaks itself is run by `make verify`), `backend/tests/unit/test_single_client_modules.py` (NFR-12).
- `docs/TEST_PLAN.md`: the six web test paths now point at `web/tests/real/`.

## Real bugs these tests found (fixed in the same push)
1. `web/lib/api/schema.d.ts` was stale against the merged API (FR-DB-6 test failed) -> regenerated (committed in FIX-01).
2. Call detail (and run detail / overview loading states): React hydration error #418 on real data. `PageHeader` rendered a `<div>` skeleton inside a `<p>`; now a `<div>` (`web/components/ui/layout.tsx`).

## Results
- `playwright_real.txt`: 21 passed. `pytest_contract.txt`: 38 passed (contract + single-client). `tsc --noEmit` and `eslint` clean.
- Reproduce: start the stack, seed, run any evaluated call, `npm run build && PAREEKSHA_API_URL=<api>/api/v1 PAREEKSHA_API_KEY=<key> npx next start -p 3200`, then
  `REAL_WEB_URL=http://127.0.0.1:3200 REAL_API_URL=<api>/api/v1 PAREEKSHA_API_KEY=<key> SHOT_DIR=../proof/QA-04/screenshots npm run test:real`; `pytest backend/tests/contract backend/tests/unit/test_single_client_modules.py`.

## Not covered (honest)
Run-detail "new evaluated call appears < 2 s without reload" (live SSE) and the dialect heatmap with data: no live run was in flight and no dialect report exists in this stack. `playwright.config.ts` mock suite was not re-run in full (needs its own build on :3100); only lint/typecheck.
