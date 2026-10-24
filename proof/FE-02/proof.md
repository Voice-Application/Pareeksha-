# FE-02 proof: Agents, Scenarios, Personas, Noise profiles

Branch `task/FE-02` (from `claude/amazing-einstein-agkccc` @ 51b62cd). Commit SHA is in the final report (`git log -1 task/FE-02`). Status: done-unverified (R2).

## What was built (`web/`)
Built only from `app/tokens.css` (DES-01). No gradients, no emoji, no shadows on panels (only on floating layers), lucide icons at stroke 1.6, light and dark via the `.dark` class (theme toggle in the topbar, stored choice, else system, applied before paint). Geist and Geist Mono come from the `geist` npm package (local fonts, no network at build).
- Shell: grouped sidebar (Build, Evaluate, Operate), 48px topbar, theme toggle, slide-over navigation under 861px, skip link, toasts (`aria-live`). `lib/nav.ts` keeps the same hrefs and labels as FE-01.
- Shared UI (`components/ui/`): Button, PageHeader, Panel, Chip, DataTable (real `<table>`, sortable, stacked cards at phone width), FilterBar (URL-backed), Field primitives (text, number, textarea, select, radiogroup Segmented, Switch, Slider, TagInput, Repeater, KeyValueList), Sheet and Dialog on native `<dialog>` (focus trap, Esc, focus return), ConfirmDialog, RowMenu (keyboard menu), Skeleton, EmptyState, ErrorPanel, PageError, Strip, audio PreviewBar, RowPlayButton, FileDropzone.
- API layer: `lib/api/call.ts` wraps the generated openapi-fetch client (`lib/api/client.ts`) and turns every non-2xx into `ApiError` (06-api-spec error shape; BFF `{"error": "..."}` string also handled). Browser calls only `/api/proxy/...`; no key anywhere in client code (FE-01 bundle-scan test still passes).
- **Agents** `/agents`, `/agents/new`, `/agents/[id]`: list (search, adapter and language filters, show archived switch, last run, session connection result, row menu Edit/Test connection/Archive with confirm), full-page form with Basics, Connection, Rules the judge checks (disclosures, forbidden phrases with live regex preview, tools, bias list), danger zone, sticky ConnectionTest panel (running with cancel, pass strip, fail strip with one fix per error word, "Result is for the previous settings"), Save and test, unsaved-changes guard, archived agents read-only.
- **Scenarios** `/scenarios`, `/scenarios/new`, `/scenarios/[id]`: list (agent and tag filters sent to the API, source and search in the client, promoted link to source call, Duplicate, Delete with 409 dialog listing runs), editor with the four sections, tool order list and "Required order" switch, SamplePanel (criteria checklist, facts table, three non-blocking warnings), promoted banner, Generate with AI Sheet (setup with mix that always sums to the count, polling, partial strip, failed with Try again, draft review with per-draft Edit dialog, `Save N selected` via `POST /scenarios:bulk`, confirm on close with unsaved drafts).
- **Personas** `/personas` (+ `?edit=<id|new>` Sheet) and `/personas/[id]`: list (language filter to the API, code-mix, emotion, interrupts, search, sort), row play button (one clip at a time), 0-3 neutral pips, seed chip; editor in the order of FR-PE-1, duplicate-voice warning, preview bar, delete with 409 dialog, dirty-close confirm.
- **Noise profiles** `/noise-profiles` (+ Sheet) and `/noise-profiles/[id]`: list sorted clean to hostile by default (SNR bar, loss and clip chips only when on), row preview; editor with slug validation, SNR disabled without background, 16 kHz + bandpass warning, preview "Sample clip" / "My clip" (FileDropzone, WAV/MP3, 10 MB) with Original/Processed buttons.
- `STUB(FE-02)` markers removed (`grep -rn "STUB(FE-02)" web/app web/components web/lib web/tests` returns nothing). Other STUBs (FE-03, FE-05) are untouched.

## Reproduce
```
cd web && npm ci
npm run lint && npm run typecheck && npm run build
PW_CHROMIUM_PATH=/opt/pw-browsers/chromium-1243/chrome-linux64/chrome npx playwright test
npm run gen:api:check -- --from ../proof/FE-01/openapi.json      # schema.d.ts unchanged by FE-02
```
Expected: lint and typecheck exit 0, build lists `/agents`, `/agents/[id]`, `/agents/new`, `/scenarios`, `/scenarios/[id]`, `/scenarios/new`, `/personas`, `/personas/[id]`, `/noise-profiles`, `/noise-profiles/[id]`; Playwright `153 passed`, 0 failed, 0 skipped. Playwright rebuilds and starts `next start` itself (set `PW_REUSE=1` to reuse a running server when iterating locally). Screenshots are rewritten to `proof/FE-02/screenshots/` by `tests/screens.spec.ts`.

## Results (real output in this folder)
| Check | Result | File |
|---|---|---|
| ESLint (`eslint .`, no disabled rules) | exit 0 | `lint.log` |
| `tsc --noEmit` | exit 0 | `typecheck.log` |
| `next build` | exit 0, 22 routes | `build.log` |
| Playwright | 153 passed, 0 failed, 0 skipped, 0 flaky | `playwright.log` |
| `gen:api:check` against the FE-01 OpenAPI | up to date | `gen-api-check.log` |
| Screenshots | 48 PNG: 10 views x light and dark, 12 loading/empty/error x light and dark, 4 phone-width | `screenshots/` |

Playwright coverage: FE-01 smoke (20, unchanged, still green) + agents 25 + scenarios 18 + personas 15 + noise profiles 12 + screens 63 (screenshots, axe WCAG 2.0/2.1 A and AA with no serious or critical violation on six pages in both themes, no gradient/emoji/panel-shadow scan, keyboard focus ring, theme persistence, phone layout with no horizontal page scroll). Per page the tests cover loading, empty, filtered empty, error with Retry, populated list, create, edit, validation, delete or archive including 409, and keyboard operation of the row menu and radiogroups.

## Real-data screenshot step: PENDING API-02
The CRUD handlers (API-02) are not available: `task/API-02` currently holds only the API-01 work (models, migration, auth), no routers. So all tests and screenshots use **Playwright route fixtures in `web/tests/support/mock-api.ts`** (test code only, synthetic data, never imported by app code). The pages call the real BFF proxy and the real generated client; only the network response is faked. Screenshots therefore show fixture rows (for example "EMI Reminder Bot"), not seeded database rows.
Pending once API-02 merges: run the app against the real backend (`make demo` seed: 20 personas, 8 noise profiles, mock agent) and re-take `agents-list`, `scenarios-list`, `personas-list`, `noise-profiles-list` light and dark. No code change is expected; the shapes come from the generated `schema.d.ts`.

## Not built, and why (each is a data gap, not hidden)
- Agents "demo" chip and "last connection result": the agent object has no seed or last-test field (G-4). The Connection column shows results of tests run in the current session, else "never tested".
- Scenarios "Used in": no usage count in the API (G-5). Shows a dash with a tooltip.
- Personas and noise profiles preview of unsaved values: needs `POST /personas:preview` / `/noise-profiles:preview` (G-6). The preview button is disabled while the form has unsaved changes and says why. No "from cache" label (the API reports nothing about caching).
- Persona "behaviour" chip and per-voice play button in the voice select: no field or voice-sample endpoint. Noise preview spectrum strip and A/B for the sample clip (the API returns only the processed sample): A/B is offered for "My clip" only.
- Error "request id": the contract defines no request-id header; the id is shown only if the response carries `x-request-id`.
- Archive is not optimistic: the list refetches after the API confirms, and a failure shows the retry toast.
- Scenario/persona/noise 409 dialogs assume the run list is in `error.details.runs` (`[{id, name}]`); without it they show only the API message.
