# 8. Run detail  `/runs/[id]`

Requirements: FR-DB-2 (Must), FR-RN-10, live SSE. Acceptance: renders a 40-call run in under 3 s; a newly evaluated call appears within 2 s without a reload. Purpose: see how a run went, where the failures cluster, and jump to the worst calls.

## Layout

```
EYEBROW  Run  Prompt v3 baseline  |  EMI Reminder Bot  |  matrix  |  [* Live]
TITLE    4 of 12 calls failed, 2 critical                         [Cancel] [Re-run] [Compare]
         Finished 14 min ago. 3 calls need human review. Top failure: asr_misrecognition x2.
+- StatTile x6 -------------------------------------------------------------------------+
| Pass rate 67% | Critical 2 | Mean score 78.4 | Latency p50 1.1 s | p95 2.3 s | Barge-in 0.5 |
+----------------------------------------------------------------------------------------+
+- Panel: Matrix (Heatmap) ------------------------------+ +- Panel: Score distribution --+
| rows: scenarios, columns: personas, [Line v] selector   | | histogram 10-pt bins + pass  |
| cell = overall score, link to call                      | | line; counts per bin         |
+--------------------------------------------------------+ +- Panel: Top failure types ----+
                                                            | TagChip + count bars          |
+- Panel: Calls (DataTable) -------------------------------------------------------------+
| Scenario  Persona  Line  Status  Score  Verdict  Flag  Tags  Latency p95  Duration      |
+----------------------------------------------------------------------------------------+
```
Header title is generated from `summary`: "{failed} of {total} calls failed, {critical} critical" (or "All {n} calls passed", or "Run is {done} of {total} done" while running).

## Matrix heatmap
- Rows = scenarios, columns = personas. With more than one noise profile or repeat, a `Line` `SegmentedControl` above the grid picks the line (`All` shows the worst score across lines in the cell with a small `x3` badge; opening the cell lists the underlying calls in a Popover).
- Cell: 56x40 minimum, score fills with the score scale, value in mono, 3px radius, 2px gap. Critical cells carry a 6px solid triangle in the top-right corner (shape, not just colour). Cells for items not yet evaluated: `--score-na` with status glyph (clock for queued, spinner for in progress, cross for error).
- Hover or focus shows a Tooltip: scenario, persona, line, score, verdict, top tag. Click goes to `/calls/{id}`.
- Sort controls: rows by worst score (default) or title; columns by worst or name.
- Legend below with the five steps and the pass-line tick.
- Keyboard: arrow keys move between cells (`role="grid"`), Enter opens.

## Live behaviour (SSE)
- `LiveIndicator` shows `Live`. Events: `snapshot` replaces state; `item.status` updates a cell's glyph; `call.evaluated` fills the cell with its score, flashes `--accent-tint` for 800 ms, and updates tiles and distribution; `run.completed` swaps the header title and stops the pulse.
- On disconnect: "Reconnecting", then 5 s polling of `GET /runs/{id}` and `/items`.
- Respect `prefers-reduced-motion` (no flash, just value change).
- Header actions while running: `Cancel` (ConfirmDialog). After completion: `Re-run` (opens wizard prefilled), `Compare` (opens compare with this as head and the previous run of the same agent as base, if any), `Export report` (`GET /runs/{id}/report`, Could F19; hidden if not enabled).

## Calls table
Same data as the heatmap in list form; default sort worst score first; filters: Verdict, Flag (needs review), Tag, Status. Rows link to the call. Flag column shows `FlagChip` icon-only with tooltip of the reasons.

## Components
`PageHeader`, `LiveIndicator`, `StatTile` x6, `Heatmap`, `SegmentedControl`, `Histogram` (chart style per direction section 5), `TagChip`, `DataTable`, `StatusPill`, `VerdictBadge`, `FlagChip`, `ProgressBar`, `ConfirmDialog`, `Popover`.

## Data
`GET /runs/{id}` (progress, summary), `GET /runs/{id}/items`, `GET /runs/{id}/events` (SSE through the proxy), `POST /runs/{id}/cancel`. Per-item top tag and latency p95 are not in `items`: gap G-7 (design shows dash if absent).

## States
- **Empty (run has zero items or the table filter hides everything):** zero items: strip "This run has no calls. The matrix was empty after filtering." with `Re-run`; filtered: standard filtered empty with Clear.
- **Queued (no items yet):** title "Run queued"; tiles dashes; heatmap shows a skeleton grid of the expected size (rows x columns known from the request, `item_count` from creation); calls table skeleton; banner "Waiting for the planner" with a LiveIndicator.
- **Running:** as above; `ProgressBar` "7 of 12" under the header, tiles marked "so far".
- **Completed with failures / all passed:** as above; an all-pass run shows a quiet neutral-teal strip "No failures. 12 of 12 passed." (no confetti).
- **Cancelled:** title "Run cancelled after 7 of 12 calls"; unfinished cells show `--score-na` with dash; summary tiles use finished calls only and say so.
- **Run error (planner failed or all items errored):** `--fail-tint` strip with cause and `Re-run`; heatmap shows the error glyph cells.
- **Item error (some calls errored):** cell shows error glyph; table row `StatusPill error` with a reason tooltip; tiles exclude errored calls and say "2 calls errored, not scored" with a link that filters the table.
- **Loading:** header skeleton, six tile skeletons, heatmap skeleton sized to the grid, 8 table rows.
- **Error:** run not found (404 page error); summary failure keeps heatmap if items loaded; SSE failure per shared 5.4.
- **Large runs (40+ calls):** the heatmap scrolls inside its panel; rows virtualised in the calls table beyond 100 rows.
