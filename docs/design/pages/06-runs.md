# 6. Runs  `/runs`

Requirements: FR-RN-1, FR-RN-10, FR-DB-1 (Must). Purpose: history of every launch, with enough numbers to choose which one to open or compare.

## Layout

```
EYEBROW 12 runs for EMI Reminder Bot
TITLE   Runs                                            [Compare] [New run]
[search] [Agent v] [Kind v: matrix|regression|dry_run] [Status v] [Date v]
+-- DataTable ----------------------------------------------------------------------+
| [] Name                 Kind        Status        Calls  Pass rate        Crit  Mean  When     |
| [] Prompt v3 baseline   matrix      completed     12     67%  Meter       2     78.4  14 min   |
| [] Nightly regression   regression  running       7/12   ...                                    |
+-----------------------------------------------------------------------------------+
```
- Checkbox column: selecting exactly two rows enables `Compare` (base = older). Otherwise `Compare` is disabled with a tooltip "Select two runs".
- Pass rate cell: mono percent plus a 56px `Meter`. The fill uses the score-scale step for that percent (the same bands as overall scores), so a bad run stands out; the number is always printed.
- `Crit` cell is `--fail-fg` with a cross icon when above 0; zero is shown as a muted `0`.
- Running rows show `StatusPill running` and progress `7/12` with a 4px `ProgressBar` instead of the pass rate; the row updates through a 5 s poll of `GET /runs` (the SSE stream is only for the detail page).
- Regression kind rows show a suite verdict (`suite_passed`): `pass` or `fail` VerdictBadge in the Pass rate column's place.
- Row menu: Open, Compare with..., Cancel (only while queued or running; ConfirmDialog "In-flight calls will hang up cleanly. Cancel run?"), Copy id.

## Components
`PageHeader`, `FilterBar`, `DataTable` with checkbox column, `StatusPill`, `ProgressBar`, `Meter`, `VerdictBadge` (suite), `ConfirmDialog`.

## Data
`GET /runs?agent_id=` (paginated by cursor), `POST /runs/{id}/cancel`. Status/kind/date filters are client-side until the API supports them (gap G-1).

## States
- **Empty (first use):** "No runs yet. A run sends synthetic callers to your agent and scores every call." Primary `New run`; secondary `Run the regression suite` shown only when regression tests exist.
- **Filtered empty:** standard.
- **Loading:** 8 skeleton rows.
- **Error:** list-level `ErrorPanel`; cancel failure Toast with Retry (409 "already finished" shows an info Toast and refreshes the row).
- **Cancelling:** row pill reads `cancelling` (neutral, spinner) until status flips, up to 10 s (FR-RN-10); after 15 s shows "Cancel is taking longer than expected".
- **Failed run (status error):** `StatusPill error`, Pass rate shows dash, caption "Planner failed" if the API gives a reason; row links to the run detail where the reason is shown.
