# 7. New run wizard  `/runs/new`

Requirements: FR-RN-1 (Must), FR-RN-2 cost estimate and budget (Should; first thing dropped if FE-03 slips, SCOPE), FR-RN-11 dry run (Should), also `?regression=1` for the regression suite (FR-RG-2). Purpose: choose the matrix, see its size and cost, then launch with one click.

## Layout: one page, four steps in a left rail, live summary on the right

```
TITLE  New run                                              (no primary action in header)
+- Steps ---+ +- Step panel ------------------------------------+ +- Summary 408 -----------+
| 1 Agent   | |                                                 | | Matrix  3 x 2 x 2 = 12     |
| 2 Scenar. | |  (content of current step)                      | | Repeats 1                  |
| 3 Callers | |                                                 | | ---------------------------|
| 4 Lines   | |                                                 | | Estimated cost  INR 31.50  |
| 5 Review  | |                                                 | | Budget left     INR 480   |
+-----------+ +-------------------------------------------------+ | [Create run]              |
                                                                  +----------------------------+
```
Steps are tabs in a vertical list, not a forced linear flow: users may jump. A step shows a check when valid and a count ("3 selected").

1. **Agent:** radio list of non-archived agents (name, adapter, languages); selecting loads scenarios for that agent.
2. **Scenarios:** table with checkboxes, filter by tag/source, `Select all`, shows max turns. At least one.
3. **Personas:** table with checkboxes, language filter, preview-play button per row. A warning chip appears if a chosen persona's language is not in the agent's languages ("Agent does not list hi-IN").
4. **Noise profiles:** checkbox list with SNR bar; quick presets: `Clean + street + market` as a one-click (just selects three profiles, no hidden logic).
5. **Review and options:** name (auto-suggested "Run {date}"), repeats (1-5), concurrency (default 3, 1-5, helper "Per-run cap"), seed (number, "Same seed gives the same first utterance and noise"), dry run switch ("Text only. Skips TTS and STT. Costs no Gnani credits. Needs a glass-box agent."; disabled with explanation if the agent is not glass-box).

## Summary panel (sticky, updates live)
- Matrix expression `scenarios x personas x lines x repeats = N calls` in mono, N large (hero number). N above 60 shows an amber note "Large run: about {minutes} min at concurrency {c}" using the NFR-1 rule of thumb stated in the UI as an estimate.
- Cost estimate rows (TTS seconds, STT seconds, judge calls, caller LLM calls, total in rupees) come from the API. `POST /runs` only returns the estimate after the run exists (gap G-3), so the design needs a dry estimate: `POST /runs:estimate` with the same body, returning the `estimate` object and `item_count`. Until it exists, the panel shows the matrix size only and the line "Cost estimate appears after you create the run"; FE-03 can then cut the estimate cleanly (SCOPE note).
- Budget: remaining budget from `GET /usage`, `Meter` of estimate against remaining.
- `Create run` primary. Disabled until steps 1-4 each have a selection; the disabled reason is listed ("Select at least one persona").

## Over-budget handling
`POST /runs` returns `402 budget_exceeded` with the estimate. The page shows an amber strip in the summary: "Estimated INR 640 exceeds the remaining INR 480." with two actions: `Reduce the matrix` (scrolls to step 1-4) and `Run anyway` (destructive-outlined; opens ConfirmDialog stating both numbers; sends `confirm_over_budget: true`).

## After create
Navigates to `/runs/{id}` immediately (the API returns `item_count`); the run detail shows the queued state.

## Data
`GET /agents`, `GET /scenarios?agent_id=`, `GET /personas`, `GET /noise-profiles`, `GET /usage` (budget), `POST /runs` (returns `item_count` and `estimate`), `POST /runs:regression` and the regression test list (gap G-12) in regression mode.

## Components
Vertical `Stepper`, `DataTable` with checkboxes, `FilterBar`, `SegmentedControl`, form primitives, `SummaryPanel` (matrix expression, cost rows, budget `Meter`), `ConfirmDialog`, `Button`.

## States
- **Empty prerequisites:** if there are no agents, scenarios, personas or profiles the step shows an EmptyState with the link to create one in a new tab ("No scenarios for this agent. Create a scenario").
- **Loading:** step tables skeleton; summary shows dashes.
- **Error:** list failure in a step shows `ErrorPanel` for that step only; create failure (5xx) shows an error strip above the Create button with Retry; the selections are kept.
- **Validation:** per step as above; repeats and concurrency numeric limits; unsaved selections survive a reload through the URL (`?agent=&s=&p=&l=` ids, capped at 2000 characters) so QA and CLI users can deep-link.
- **Regression mode** (`?regression=1`): steps 2-4 replaced by a single read-only list "Blocking regression tests (4)" with persona and line shown per test; only agent and options are editable. Title becomes "Run regression suite".
