# Page specs: shared patterns (DES-01)

Applies to every page spec in this folder. Visual language: `../direction.md`. Tokens: `../tokens.css`. Reference render of the finished look: `../mock-call-detail.html`. Scope and priorities: `docs/SCOPE.md` (Must / Should / Could). Requirement IDs: `docs/02-requirements.md`.

Specs say what is on the page, which component renders it, which endpoint feeds it, and what the three non-happy states look like. They do not prescribe React structure. FE chooses file layout; names below are the component names to use so QA and DES can talk about the same thing.

## 1. Page index

| # | Page | Route | Priority (SCOPE) | Spec |
|---|---|---|---|---|
| 1 | Overview | `/` | Must (FR-DB-1) | `01-overview.md` |
| 2 | Agents | `/agents`, `/agents/new`, `/agents/[id]` | Must | `02-agents.md` |
| 3 | Scenarios | `/scenarios`, `/scenarios/[id]` | Must | `03-scenarios.md` |
| 4 | Personas | `/personas`, `/personas/[id]` | Must | `04-personas.md` |
| 5 | Noise profiles | `/noise-profiles`, `/noise-profiles/[id]` | Must | `05-noise-profiles.md` |
| 6 | Runs | `/runs` | Must | `06-runs.md` |
| 7 | New run wizard | `/runs/new` | Must (cost estimate: Should) | `07-new-run-wizard.md` |
| 8 | Run detail | `/runs/[id]` | Must | `08-run-detail.md` |
| 9 | Run compare | `/runs/compare` | Should | `09-run-compare.md` |
| 10 | Call detail | `/calls/[id]` | Must (never cut) | `10-call-detail.md` |
| 11 | Audits | `/audits`, `/audits/new` | Must | `11-audits.md` |
| 12 | Dialect | `/dialect`, `/dialect/[reportId]` | Must (never cut) | `12-dialect.md` |
| 13 | Regression | `/regression` | Should | `13-regression.md` |
| 14 | Integrations (+ delivery log) | `/integrations`, `/integrations/[id]` | Must (log: Should) | `14-integrations.md` |
| 15 | DLQ | `/dlq` | Should | `15-dlq.md` |
| 16 | Calibration | `/calibration` | Should | `16-calibration.md` |
| 17 | API keys | `/api-keys` | Must | `17-api-keys.md` |

Cut order if time runs out (SCOPE): drop Should pages first. They still get a sidebar entry with an empty state that says the feature is not enabled, so FR-DB-1 "all pages reachable" stays true.

## 2. App shell

```
+--------------+--------------------------------------------------------------+
| Pareeksha    | Breadcrumb / Breadcrumb / Here        [SAMPLE|ENV chip] [theme] |  48px topbar
| Overview     +--------------------------------------------------------------+
| BUILD        |  EYEBROW                                         [Secondary]  |
|  Agents      |  Page title as a sentence                        [Primary]    |
|  Scenarios   |  one supporting sentence                                      |
|  Personas    |  +- MetaStrip ------------------------------------------+     |
|  Noise prof. |  |                                                       |     |
| EVALUATE     |  +-------------------------------------------------------+     |
|  Runs        |  +- content (panels, 24px gap) ----------+ +- aside 408 --+     |
|  Audits      |  |                                       | |              |     |
|  Dialect     |  +---------------------------------------+ +--------------+     |
|  Regression  |                                                               |
| OPERATE      |   max content width 1360, page padding 32 (16 on phone)       |
|  Integrations|                                                               |
|  DLQ         |                                                               |
|  Calibration |                                                               |
|  API keys    |                                                               |
| rubric ver.  |                                                               |
+--------------+---------------------------------------------------------------+
```

- Sidebar 232px, sticky. Group labels use the eyebrow style. Active item `--bg-selected`, weight 500. Counts (open DLQ, running runs) appear as mono numbers on the right of the item; DLQ count uses `--fail-fg` when above 0.
- Under 860px the sidebar becomes a slide-over opened from a menu button in the topbar; breadcrumb collapses to the last two segments.
- No global search in v1. Keyboard: `g` then a letter jumps to a section (g r = Runs, g a = Agents); `?` shows the list. Optional, Could.
- Theme toggle in topbar; default follows the system.
- The topbar shows a `SAMPLE DATA` chip only in design mocks; production shows the environment name when not production-like (for example `demo`).

## 3. Page header

`PageHeader`: eyebrow (context, 11px uppercase), title (26px, one sentence that states the state of the thing, not the noun when there is a finding), supporting sentence (14px muted, max 68ch), actions top right (one primary at most).

Title rules: lists use the noun plus count ("Agents", count in eyebrow: "3 active, 1 archived"). Detail pages with findings use a sentence ("Run failed 4 of 12 calls, 2 critical"). Never "Details".

## 4. Shared component catalogue

All components take tokens only. Names in bold are used by more than one page.

| Component | What it is | Used on |
|---|---|---|
| **AppShell, Sidebar, Topbar, Breadcrumbs, PageHeader** | frame | all |
| **Panel** | bordered surface, 44px header (title + aux slot), body | all |
| **MetaStrip** | `dl` strip, 3-6 cells, eyebrow label + value + small caption | 2, 3, 4, 8, 10, 11, 14 |
| **DataTable** | 36px rows, 13px text, sticky header on `--bg-sunken`, sortable columns, row click to detail, row actions in a trailing menu, mono for ids/numbers, optional checkbox column, cursor pagination ("Load more") | 2-6, 11, 13-15, 17 |
| **FilterBar** | search input + 0-3 filter selects + active-filter chips + "Clear" | tables |
| **SegmentedControl** | 2-5 mutually exclusive options | 8, 10, 12 |
| **Button** | `primary` (accent), `secondary` (surface + strong border), `ghost`, `destructive` (outlined fail); 32px; icon-only variant with `aria-label` | all |
| **VerdictBadge** | `pass`, `fail`, `critical` with icon + word. Critical is the only solid badge. | 6, 8, 10, 11, 13 |
| **FlagChip** | `needs_human_review`, outlined neutral chip with flag icon; may list `review_reasons` as mono chips. Never styled as a verdict. | 8, 10, 11 |
| **ScoreChip** | `n/4` or `0-100` filled with the score-scale step | 8, 10, 13 |
| **Pips** | 4-segment bar for a 0-4 dimension score | 10 |
| **Meter** | 8px track, filled to value, 2px ink tick at the pass line (80) | 8, 10 |
| **StatTile** | eyebrow label, mono value (20px), target caption, optional threshold icon (check/triangle/cross) | 1, 8, 10, 16 |
| **Heatmap** | grid of ScoreCells (3px radius, 2px gap, value in mono), row/column headers, legend with pass-line tick, cells are links | 8, 9, 12 |
| **TagChip** | mono failure type with icon (cross = failure tag, triangle = warning-level), optional `#turn` EvidenceRef | 8, 10, 13 |
| **EvidenceRef** | mono `#n` button; seeks audio, scrolls transcript | 10 (and links from 8, 13 as `/calls/id?turn=n`) |
| **StatusPill** | run or item status: `queued` (neutral clock), `running`/`in_progress` (accent dot, pulses unless reduced motion), `evaluated`/`completed` (neutral check), `cancelled` (neutral dash), `error` (fail cross). Unknown status renders neutral with the raw string. | 6, 8, 11, 14, 15 |
| **LiveIndicator** | "Live" dot when SSE is connected, "Reconnecting" when retrying, "Polling every 5 s" in fallback | 8 |
| **Waveform + AudioTransport** | wavesurfer.js, two speaker lanes, regions, playhead; play, time, speed (0.75, 1, 1.25, 1.5) | 10, 11, 12 (clip player), 4 (persona preview), 5 (noise preview) |
| **TranscriptTurn** | time + turn index, speaker, text (`lang` attribute set), translation line, glass-box block, evidence styling | 10 |
| **Form primitives** | text input, textarea, select, combobox, number, slider with value, switch, tag input, key-value list, language multiselect; label above, help text below, error text with icon below | 2-5, 7, 14, 17 |
| **JsonSchemaForm** | renders `config_schema` / `secrets_schema` from `GET /integrations/connectors` | 14 |
| **SecretField** | write-only; shows "Set" with a Replace button, never a value | 14 |
| **CopyField** | read-only mono value + copy button, confirms with "Copied" for 1.5 s | 14, 17 |
| **Sheet** | right-hand drawer 480px (full width on phone) for create/edit forms | 2-5, 14, 17 |
| **Dialog / ConfirmDialog** | 12px radius, `--shadow-float`, focus trap, Esc closes; destructive confirms name the object | all |
| **FileDropzone** | dashed border, accepts type/size from props, shows file name, size, remove | 11, 12, 5 |
| **ProgressBar** | determinate, 4px, accent fill, with "done / total" mono text | 8, 12 |
| **Skeleton, EmptyState, ErrorPanel, InlineError, Toast** | state components (section 5) | all |

## 5. States (apply to every page unless the page spec overrides)

### 5.1 Loading
- **First load:** skeleton shaped like the final content: `--bg-sunken` blocks, same row heights, 1.2 s opacity pulse (0.6 to 1), static under `prefers-reduced-motion`. Page header and sidebar render immediately; titles that depend on data show a 280px skeleton bar.
- **Refetch with data on screen:** keep the data, show a 2px accent progress line under the topbar; no skeleton flash.
- **Anything over 800 ms** shows the skeleton; faster loads show nothing extra.
- **Action in progress:** the button shows a 14px spinner and keeps its width; the form stays editable only where safe.

### 5.2 Empty
`EmptyState`: centred in the panel body, max 420px. Structure: 24px monochrome line icon (lucide, 1.6 stroke, `--fg-subtle`), title (16px, 500) saying what will be here, one muted sentence on why it matters, one primary button for the next action, optional secondary text link to docs. No illustrations in colour. Three flavours:
- **First-use empty** (nothing created yet): CTA creates the first one. Example: "No agents yet. An agent is the voice bot you want to test. Add an agent."
- **Filtered empty** (filters hide everything): "No runs match these filters." + "Clear filters" button; keep the FilterBar visible.
- **Not applicable / not enabled:** states the reason and the owner ("Regression runs are not enabled in this build"). No CTA.

### 5.3 Error
- **Panel error** (one request failed): inside that Panel, a `--fail-tint` strip with cross icon, one-line cause in plain words, `Retry` button, and the request id in mono (`req_...` from the response header). Other panels keep working.
- **Page error** (the primary resource failed, 404, 403): replaces the content area, keeps shell. 404: "This call does not exist or was deleted" + link back to the list. 403: names the scope needed (`runs:write`). 5xx or network: "The API did not respond" + Retry + a link to `/health` status.
- **Field error:** below the field, icon + text in `--fail-fg`, field border `--fail`; on submit focus moves to the first invalid field and an error summary appears at the top of the Sheet/Dialog (`role="alert"`).
- **Conflict / budget:** HTTP 402 `budget_exceeded` and 409 are shown as a warning strip (amber icon) with the numbers from the response and the explicit override action; they are not generic errors.
- **Optimistic actions** (archive, discard, redeliver) roll back with a Toast "Could not archive: reason" and a Retry action.
- Never show raw stack traces or JSON. Show `error` + `detail` fields when the API provides them (06-api-spec error shape), in plain sentence case.

### 5.4 Partial and stale
- A missing value is a dash (`-`) in `--fg-subtle`, with a tooltip stating why ("Not computed: no tool calls recorded").
- A running or transcribing item shows its StatusPill and an indeterminate state in the cells that will fill in later, not zeros.
- If SSE drops, the page shows "Reconnecting" in the LiveIndicator, then falls back to 5 s polling and says so. Data on screen is kept and marked stale (timestamp "Updated 12 s ago") after 15 s without an update.

## 6. Behaviours common to lists

- Default sort: most recently updated first, except where a page says otherwise.
- URL holds state: filters, sort, selected tab and page (so links are shareable and QA can open a state directly).
- Row click opens detail; a trailing `...` menu holds secondary actions. The whole row is not a link when it also contains links (use a leading name link instead).
- Bulk selection only where a page asks for it.
- Archive replaces delete for agents; other deletes ask for confirmation naming the object.
- Times are shown as relative ("12 min ago") with the absolute ISO time in a tooltip and `<time datetime>`. Durations as `mm:ss`; latencies as `1.1 s` below 10 s, otherwise `12 s`. Money in rupees with the `₹` sign and thousands grouping as in the Indian system only if the locale is `en-IN` (default).

## 7. Copy rules

Sentence case. Verbs on buttons ("Create run", not "Submit"). No exclamation marks. Say "caller" for the synthetic or real person on the phone and "agent" for the bot under test, everywhere. Failure tags are shown as their API strings in mono (`asr_misrecognition`), with a plain-language tooltip from a single dictionary in FE (`failureTypeCopy`).

## 8. Accessibility checklist (QA can test each)

- All text meets the contrast table in `validate_palette.log`; no information by colour alone (verdicts and thresholds always add icon + word).
- Every interactive element reachable by keyboard in reading order; visible 2px focus ring (`--focus-ring`, 2px offset).
- Tables use real `<table>`; heatmaps use a `role="grid"` with `aria-label` on each cell ("Scenario Already paid, persona Manju, score 52, fail").
- Waveform has a text alternative (the transcript) and keyboard controls: Space play/pause, Left/Right 5 s, `j`/`k` previous/next turn, `[`/`]` previous/next evidence.
- Dialogs trap focus and return it to the trigger. Toasts are `aria-live="polite"`; errors `role="alert"`.
- Target size at least 32px (24px minimum for dense row actions with 8px spacing).
- Respect `prefers-reduced-motion` and `prefers-color-scheme`.
- Kannada and Devanagari text carries `lang="kn"` / `lang="hi"`.

## 9. Responsive rules

- Breakpoints: 1180 (aside stacks under content), 860 (sidebar to slide-over), 560 (phone).
- At 560 and below: tables become stacked cards (name, key status, key number, chevron); Sheets go full-screen; the Heatmap scrolls horizontally inside its panel (the only allowed horizontal scroll) with sticky row headers; the page never scrolls sideways.
- Primary action in the PageHeader collapses to an icon button at 560 and a floating bottom bar is NOT used.

## 10. Data and security notes for FE (design-relevant)

- The browser only talks to `/api/proxy/...`; the UI never renders or stores an API key except the one-time reveal on the API keys page (kept in component state only, cleared on dialog close).
- Secrets (integration tokens, signing secrets) are write-only everywhere; the UI shows "Set" and offers Replace.
- Audio is streamed with `Range`; the player must not load the whole file before play.
- PII: phone numbers and contact ids shown masked (`+91 XXXXXXXX00`) as the API returns them; do not add unmasking.
- Sample and demo data are labelled as such in the UI wherever it is seeded (`demo` badge), never presented as customer data.

## 11. Data the pages need that `06-api-spec.md` does not list (for TL, not changed by design)

Contracts are frozen after TL-01 (R5); these are reported as issues, not edited. Each page spec degrades to a dash or a disabled control when the data is missing, as noted there.

| ID | Needed by | What is missing |
|---|---|---|
| G-1 | Runs | server-side filters on `GET /runs` for status, kind and date range |
| G-2 | Overview | list of evaluations or calls with `needs_human_review = true` (recent, with `review_reasons`) |
| G-3 | New run wizard | a dry estimate before creating a run (`POST /runs:estimate`) |
| G-4 | Agents | last test-connection result on the agent object |
| G-5 | Scenarios | usage count (runs and regression tests referencing a scenario) |
| G-6 | Personas, Noise profiles | preview with unsaved values (`POST /personas:preview`, `POST /noise-profiles:preview`) |
| G-7 | Run detail | per item: top failure tag, latency p95, flag; or `GET /runs/{id}/calls` with that summary |
| G-8 | Run compare | the agent config snapshot of a run (`test_runs` stores it per `05-database-design.md`) exposed on `GET /runs/{id}` |
| G-9 | Call detail | scenario, persona and noise profile titles on the call object (or the run item) |
| G-10 | Audits | list endpoint for uploaded and imported calls (`GET /calls?source=upload,webhook`) with status, score, flags |
| G-11 | Dialect | list datasets and reports; per-clip results for drill-down (`GET /dialect-reports/{id}/clips?dialect=&condition=`) |
| G-12 | Regression | list, patch and delete for `regression_tests`, with last score and last result |
| G-13 | Calibration | list of human-reviewed evaluations and a "next unlabelled call" source |

If any of these will not be built, tell DES which page spec to cut down (order of impact: G-12, G-10, G-11, G-7).
