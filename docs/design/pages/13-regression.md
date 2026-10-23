# 13. Regression  `/regression`

Requirements: FR-RG-1, FR-RG-2, FR-AU-5, F14 (Should). Purpose: keep the failures you fixed fixed. Regression tests are scenarios promoted from failed calls, pinned to a persona and line with a baseline score. The `blocking` ones form the suite that CI runs.

## Layout

```
EYEBROW  EMI Reminder Bot | 4 blocking, 2 scheduled, 1 manual        [Agent v]
TITLE    Last suite run failed 1 of 4 blocking tests                 [Run regression suite]
         Run "Nightly regression" 3 h ago. Blocking test "Wrong amount read-back" scored 52, baseline 80.
+-- Panel: Suite status strip --------------------------------------------------------------+
| Last 10 suite runs: row of 10 ScoreCells (suite pass = teal, fail = cross glyph), date      |
+------------------------------------------------------------------------------------------+
+-- DataTable: Regression tests ---------------------------------------------------------+
| Name (scenario)           Failure type        Status     Persona / Line      Baseline Tol  Last score  Last result  Source call |
| Wrong amount read-back    asr_misrecognition  blocking   Manju / market 5dB  80       5    52          fail        #17         |
+-------------------------------------------------------------------------------------+
```
- Title states the last suite result (`suite_passed` on the latest regression run); with no suite run yet: "No suite run yet".
- Table filter: Status (`blocking`, `scheduled`, `manual`), failure type, agent. Row actions: Change status (inline `Select` in the Status cell), Edit baseline and tolerance (inline popover), Open scenario, Open source call, Run this test (creates a one-item regression run), Remove (ConfirmDialog).
- `Last result` uses `VerdictBadge`; "pass" means score >= baseline minus tolerance and no critical failure (FR-RG-2), and the tooltip states the arithmetic ("52 is below 80 - 5 = 75").
- `Source call` is a link, absent for hand-made tests.
- `Run regression suite` opens the wizard in regression mode (`/runs/new?regression=1`) with the agent preselected, and shows how many blocking tests will run. If zero blocking tests it is disabled with a tooltip.

## Components
`PageHeader`, agent `Select`, `Panel`, `SuiteHistory` strip, `DataTable`, inline `Select` and number popover, `VerdictBadge`, `TagChip`, `ConfirmDialog`, `Button`.

## Data
`POST /runs:regression`, `GET /runs?agent_id=&kind=regression` (history, suite result), promote results from `POST /calls/{id}/promote`. Listing and editing regression tests, plus last score per test: gap G-12 (no list/patch endpoint in `06-api-spec.md`; table cannot render without it).

## States
- **Empty:** "No regression tests yet. Promote a failed call and it becomes a test that future runs must not fail." Primary `Open failed calls` (links to Runs filtered to failures); no creation form (tests only come from calls or the CLI).
- **No suite run yet:** title as above; strip shows an EmptyState line "Run the suite to see its history."
- **Running suite:** title "Suite running, 2 of 4 done" with a link to the run; the table shows `StatusPill running` per test.
- **Suite passed:** quiet strip "All 4 blocking tests pass." with the date.
- **Loading:** skeleton for the strip (10 cells) and 5 rows.
- **Error:** list standard; status change failure rolls back with Toast; removal of a test used by a running suite refused with the reason.
- **Tolerance edge:** baseline 0 or above 100 blocked; tolerance over 20 warns "Large tolerance hides regressions".
