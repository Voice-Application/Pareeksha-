# 9. Run compare  `/runs/compare?base={id}&head={id}`

Requirements: FR-RG-3, F15 (Should). Purpose: after a prompt or agent change, answer "what got worse?" first. Regressions are listed before improvements.

## Layout

```
EYEBROW  Base: Prompt v2 (12 Oct)   ->   Head: Prompt v3 (14 Oct)   [Swap]
TITLE    2 cells regressed, 3 improved, 7 unchanged                [Open head run]
         Pass rate 75% -> 67%.  Newly failing: Already paid x Manju (86 -> 52).
+- StatTile x4: Pass rate (delta) | Critical (delta) | Mean score (delta) | Latency p95 (delta) -+
+- Panel: Changed cells (DataTable, regressions first) ------------------------------------------+
| Scenario  Persona  Line   Base   Head   Delta          Status                                    |
| Already paid  Manju  market  86   52   -34 (bar)       newly failing  [critical]                 |
+--------------------------------------------------------------------------------------------------+
+- Panel: Diff heatmap ------------------------------------+ +- Panel: What changed in the agent --+
| same grid as run detail, cell shows head score and a     | | snapshot diff of agent config:     |
| signed delta; unchanged cells are muted                  | | description, disclosures, tools    |
+----------------------------------------------------------+ +-------------------------------------+
```
- Header run pickers are two `RunSelect` comboboxes (searchable, showing name, date, pass rate). Changing either updates the URL.
- Delta tiles: mono signed value with an arrow icon and word ("down 8 points"); good/bad direction uses the verdict icons (cross/check), not red/green arrows alone. For critical failures an increase is bad; for latency an increase is bad; for pass rate an increase is good; the tile states direction explicitly in its caption.
- Changed cells table sorted: newly failing, then regressed by delta ascending, then improved, then unchanged (collapsed under "7 unchanged", closed by default). Delta bar: 64px diverging bar centred on zero, filled with `--score-1/2` for negative and `--score-5` for positive, plus the signed number.
- Diff heatmap: head score fill as in run detail; delta overlay in the lower-left (`-34`, mono 10px) and a 2px outline on newly failing cells (outline, not colour only). Unchanged cells at 45% opacity with value still readable (contrast kept at >= 4.5:1 by drawing the text in full strength).
- Agent snapshot diff panel: because runs snapshot the agent config, show the differences in the agent description, mandatory disclosures, forbidden phrases and tools as a compact two-column diff (added lines with a plus icon, removed with a minus icon, not colour alone). If snapshots are identical: "The agent config was identical in both runs." Data: gap G-8 (snapshot not exposed by `GET /runs/{id}`).
- Cells link to a side-by-side call pair view is Could and not specified; each changed row has two links, `Base call` and `Head call`.

## Components
`PageHeader`, `RunSelect`, `StatTile` with delta, `DataTable`, `DeltaBar`, `Heatmap` (diff mode), `DiffList`, `Button`.

## Data
`GET /runs/compare?base=&head=` (cells with `base_score`, `head_score`, `delta`, `newly_failing`, summary counts), `GET /runs/{id}` for both (summary tiles).

## States
- **Missing parameters:** "Choose two runs to compare" with two `RunSelect` and `Compare` button; no error.
- **Same run twice:** inline notice "Base and head are the same run."
- **Different agents:** amber strip "These runs used different agents. Differences may not come from a prompt change." Comparison still shown.
- **No overlapping cells:** EmptyState "These runs share no scenario, persona and line combination" + advice to re-run with the same matrix.
- **No change:** title "No differences" and an all-muted grid.
- **Loading:** tiles and table skeletons. **Error:** 404 for a run id names which id is missing; compare failure shows `ErrorPanel` with Retry while the tiles (from the two run summaries) remain.
- **Incomplete run:** if either run is still running, banner "Head is still running. Results update when it finishes" and the page polls every 5 s.
