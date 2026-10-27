# FE-05 proof: Audits, Dialect, Regression, Integrations, DLQ, Calibration, API keys

Branch `task/FE-05` from `task/FE-04`. Commit: last commit of `task/FE-05`.

## Built (all against the frozen contract)
- `/audits` list over `GET /calls?source=upload&source=import` (filters source/verdict/flag, search, 3 s poll while rows are in flight, score/verdict/flag/tag cells, link to the call) and `/audits/new` (WAV/MP3 dropzone up to 10 MB, agent, language checkboxes, stereo switch, required consent, multipart `POST /audits`, field-level errors for 413/422/403/501, "what happens next" panel).
- `/integrations` list + connector registry panel (planned connectors as plain text with a "Planned" chip), Add sheet driven by the connector's `config_schema` / `secrets_schema` (`JsonSchemaForm`, write-only `SecretField`), event filter, one-time inbound URL + signing-secret reveal with a required "I copied it". `/integrations/[id]`: Settings (secrets show "Set" + Replace, enable switch), Test connection, Delete with confirm, Deliveries tab (status filter, view sheet, Redeliver with the idempotency confirm).
- `/dlq` (status/topic/consumer filters, 15 s refetch, error and envelope JSON in a Sheet, Replay, Discard with confirm, Replay all open, healthy empty state) and `/settings/api-keys` (create dialog that becomes the one-time reveal, scope checkboxes where `admin` locks the rest, revoke with confirm, revoked view, CLI usage block).
- `/dialect` (datasets and reports) and `/dialect/[reportId]` (dialect x condition heatmap on the score scale with a WER / CER / entity accuracy selector, n and CI in every cell label, low-n hatching, generated title, selected-cell detail with worst clips, top misrecognised words, bias suggestions with copy, HTML export link), `/regression` (tests table with the tolerance arithmetic in the verdict tooltip, suite title from the last regression run, Run suite -> `POST /runs:regression`), `/calibration` (kappa / Spearman / labelled / largest-gap tiles, per-dimension MAE bars, below-target sentence, Start labelling -> next unreviewed call).
- STUB(FE-05) removed from all seven pages.

## What the real API can and cannot back today (said plainly)
| Page | Real-data status |
|---|---|
| API keys | real (`GET /api-keys`, the seeded demo key); create/revoke exercised in Playwright with the mocked API, **not** against the real stack (would mint and revoke a real key) |
| DLQ | real: one genuine dead letter (`proof/API-04/dlq_demo.py`: an unknown-run `run.requested` through outbox, planner, DLQ recorder) |
| Audits | real list of one upload-source call (real Gnani batch diarised STT + DeepSeek judge, see FE-04); **`POST /audits` is a 501 stub (EVAL-04)**, so the upload form is tested only against a mocked 501 |
| Integrations | list is real and empty; **`GET /integrations/connectors` returns `[]`** in the API image (no connector entry points registered), so Add stays disabled with a reason; test/deliveries/redeliver are INT-01 stubs (501) |
| Dialect | **all `/dialect-*` endpoints are 501 (EVAL-05)**: real screenshots show the "not enabled" state; the heatmap is verified with synthetic data in Playwright and `screenshots-synthetic/` |
| Regression | **501 (API-05)**: real screenshot shows "not enabled"; table and suite title verified with synthetic data |
| Calibration | **501 (API-05)**: same; also no list of human-reviewed evaluations (G-13), so blind mode and the disagreement table are not built |

## Reproduce
Stack, key and data as `proof/FE-03/proof.md` and `proof/FE-04/proof.md`, plus:
```
$DC exec -T api python - < proof/API-04/dlq_demo.py             # one real DLQ item
cd web && node scripts/shots.mjs ../proof/FE-05/screenshots "/audits=audits" "/audits/new=audits-new" "/dlq=dlq" "/settings/api-keys=api-keys" "/integrations=integrations" "/dialect=dialect" "/regression=regression" "/calibration=calibration"
node scripts/axe-real.mjs ../proof/FE-05/axe_real.json /audits /audits/new /dlq /settings/api-keys /integrations /dialect /regression /calibration
npm run lint && npm run typecheck && npm run build && npx playwright test
```

## Results
- `lint.log` 0; `typecheck.log` 0; `build.log` OK; `gen-api-check.log` up to date (schema regenerated against the running API in FE-03).
- `playwright.log`: full suite, **186 passed, 0 failed, 0 skipped**. 17 new FE-05 tests: DLQ list/sheet/replay/discard/empty, API key one-time reveal (key absent from DOM, storage and URL after Done; Esc does not close it), admin scope lock, revoke naming the key, audits list/empty/upload validation and 501, integrations list/add/reveal/detail/redeliver/501, dialect heatmap ranking/hatching/metric switch/cell select/501, regression table and 501, calibration tiles, below-target sentence and 501; axe wcag2a+wcag2aa on each page.
- `axe_real.json`: axe on the real pages, light and dark: **0 violations** (16 page-themes).
- `screenshots/`: real-API renders of all eight routes, light and dark. `screenshots-synthetic/`: dialect report, regression, calibration, integrations with **synthetic** data through the mocked API (these endpoints are 501 or empty on the real API); not evidence of the platform, only of the UI.
- `ui_review.md`: self-review and fixes.

## Issues
1. EVAL-04 (`POST /audits`, speaker-map), EVAL-05 (dialect), API-05 (regression, calibration, review, promote) and INT-01 (test/deliveries/redeliver) routes are still 501: FE-05 pages for them are built and tested against mocks only.
2. Connector registry is empty in the API Docker image (entry points not installed): Integrations cannot add anything on a stack built from the repo Dockerfile.
3. `GET /calls` has no file name or external id, so Audits shows the call id (gap G-10).
