# FE-03b self-review (screenshots vs docs/design/direction.md and pages/09-run-compare.md)

Reviewed `screenshots/compare-*.png` (real data, light and dark). Fixes applied (5 of the 8 allowed):
1. Latency tile with no timing in either run read "not measured to not measured": now one plain sentence ("No per-turn timing was reported in either run.").
2. Heatmap delta overlay (-36, +65) was drawn in the default text colour and unreadable on dark cells: it now uses the cell step's `--score-N-on` colour (unchanged cells use `--fg`).
3. Smoke test expected the nav label as h1; the empty state's h1 is the sentence "Choose two runs to compare" (same pattern as other sentence-title pages), so `/runs/compare` joined SENTENCE_TITLES.
4. "up 1 failures" grammar: unit is singular for exactly 1.
5. Tile direction is stated in words plus a check/cross icon (not arrow colour alone): verified in both themes, and again on the swapped view (all green/check).
No remaining differences from direction.md noted: tokens only (no raw colours), one primary action, tabular mono numbers, no colour-only status (icons and words on every status and delta, outline on newly failing).
