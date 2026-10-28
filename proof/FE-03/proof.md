# FE-03 proof: Overview, Runs, New run wizard, Run detail (live SSE + heatmap)

Branch `task/FE-03` from `origin/task/API-04` (e92e13f). Commit: last commit of `task/FE-03`.

## Built
- `/runs` list: server-side agent/kind/status filters (`GET /runs`), search, sortable columns, two-run Compare, Cancel with confirm, 5 s poll while runs are in flight, pass-rate Meter, suite verdict for regression runs.
- `/runs/new` wizard: 5 steps in a left rail, live summary (matrix `s x p x l x repeats`, cost from `POST /runs:estimate`, budget Meter), 402 over-budget strip with a `Run anyway` confirm, dry-run switch gated on glass-box, selections kept in the URL (`?agent=&s=&p=&l=&step=`).
- `/runs/[id]` run detail: sentence title from the summary, six tiles, matrix Heatmap (`role=grid`, arrow keys, line selector, worst-first sort, critical corner triangle, legend with the pass line), score histogram, top failure types, calls table (verdict/flag/status filters; flags and tags from `GET /calls?run_id=`), live updates from `GET /runs/{id}/events` through the BFF proxy (`snapshot`, `item.status`, `call.evaluated`, `run.completed`), fallback to 5 s polling after 3 failed connects, LiveIndicator states, cancel.
- `/` Overview: agent switcher (URL, localStorage as convenience), four tiles that link, worst calls, platform health (`/metrics/summary`, `/health`, 15 s poll), recent runs, needs-human-review (`GET /calls?needs_review=true`).
- Shared measurement components in `components/ui/measure.tsx`: ScoreChip, VerdictBadge (Critical is the only solid badge), FlagChip, StatusPill, Meter, Pips, ProgressBar, StatTile, TagChip, EvidenceRef.
- `web/lib/api/schema.d.ts` regenerated with `npm run gen:api` against the real running API (`gen-api-check.log`: up to date).
- `STUB(FE-03)` removed from `/`, `/runs`, `/runs/new`.

## Not built (said plainly)
- **`/runs/compare` keeps its `STUB(FE-03)`.** It is on the §10 cut list, needs a second finished run (more real-service spend) and the agent config snapshot (gap G-8). `GET /runs/compare` exists and the runs list already links to it.
- Regression mode of the wizard (`?regression=1`): `POST /runs:regression` and the regression test list are API-05 stubs (501).
- The server run summary stays empty while a run is in flight, so the tiles show values computed from the evaluated items ("so far").

## Real data used
Real stack (compose project `fe03`: Postgres, Kafka, API, planner, outbox-relay, dlq-recorder, retrier, reconciler; `python -m pareeksha.seed`). Run `Prompt v3 baseline` (3 scenarios x 2 personas x 2 lines = 12) was created with `POST /runs`; the real planner made the 12 items. The voice simulator (VOICE-05) and the evaluator/finalizer workers are not merged, so `proof/FE-04/real_calls.py` fills the items: Gnani TTS voices every turn (persona voices; the agent side is scripted in `proof/FE-04/scripts.py`), the caller track passes through the platform's `LineSimulator` for the item's noise profile, Gnani STT transcribes it, the DeepSeek judge (`evaluate_call`, rubric-2026-10-v1) scores it, rows are written with the docs/schema.sql columns and the run summary is finalised. Two more runs (`Prompt v4 candidate` queued, `Dry check` cancelled) were created through the API for the other states. Spend: `credit_use.md`.

## Reproduce
```
export BUILDX_BAKE_ENTITLEMENTS_FS=0 CA_BUNDLE=/root/.ccr/ca-bundle.crt     # sandbox behind the TLS proxy
DC="docker compose -p fe03 -f docker-compose.yml -f docker-compose.proxy.yml -f proof/FE-03/compose.override.yml"
$DC up -d --build postgres kafka kafka-init migrate api outbox-relay planner dlq-recorder retrier reconciler
$DC run --rm --no-deps api python -m pareeksha.seed                          # prints the demo key once
cd web && OPENAPI_URL=http://localhost:62800/openapi.json npm run gen:api
# create the run with POST /runs, fill it (needs GNANI_API_KEY, DEEPSEEK_API_KEY): docstring of proof/FE-04/real_calls.py
PAREEKSHA_API_URL=http://127.0.0.1:62800/api/v1 PAREEKSHA_API_KEY=<demo key> npx next start -p 3100 -H 127.0.0.1
node scripts/shots.mjs ../proof/FE-03/screenshots "/runs=runs" "/runs/<run id>=run-detail" "/=overview"
node scripts/axe-real.mjs ../proof/FE-03/axe_real.json "/" "/runs" "/runs/<run id>"
npm run lint && npm run typecheck && npm run build && npx playwright test
```

## Results
- `lint.log` eslint exit 0; `typecheck.log` tsc exit 0; `build.log` next build OK; `gen-api-check.log` up to date.
- `playwright.log`: **98 passed, 0 failed, 0 skipped** (FE-02 suites, smoke over every nav route, 13 new FE-03 tests: list, filters, compare enable, empty/error, wizard estimate and create, 402 override, heatmap links and arrow keys, live SSE fill, 404, overview, axe on each page). One FE-02 test (`scenarios.spec.ts` "filters by agent and tag") raced the URL update after `Clear` and failed under load; it now waits for the URL. `smoke.spec.ts` accepts sentence titles for pages whose h1 states the finding.
- `axe_real.json`: axe wcag2a+wcag2aa on the real pages, light and dark: **0 violations** (10 page-themes). axe found `x2` badge contrast on the heatmap; fixed.
- `screenshots/`: runs, run-detail (12 real calls), run-queued, run-cancelled, overview, wizard-scenarios, wizard-review, each light and dark.
- `ui_review.md`: the self-review and the fixes applied.

## Issues for the orchestrator
1. No simulator exists, so a run never leaves `queued` by itself; `RunOut.status` stays `queued` while items evaluate. The UI treats `queued` with progress as running.
2. `COST_*` rates are not set in the API environment, so `estimate.est_cost` is 0; the wizard shows "rates not set" instead of 0.
3. The API image has no `rapidfuzz` (needed by `evaluation/checks.py`) and registers no connector entry points (`GET /integrations/connectors` returns `[]`): Dockerfile deps / `pip install -e` missing.
