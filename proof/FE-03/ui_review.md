# FE-03 UI self-review (light + dark Playwright screenshots vs docs/design/direction.md)

Screenshots reviewed: `screenshots/runs-*`, `run-detail-*`, `overview-*`, `wizard-*` (real stack, real calls). Fixes applied, then re-shot.

1. Run detail heatmap cells did not fill the panel (inline grid, big dead area right of the matrix). Grid is now full width (direction 5: square-ish cells, 2px gap).
2. Calls table "Tags" column wrapped two or three chips per row and made rows 60px tall (breaks "dense readable data"). Now one tag plus a `+n` count with the rest in the tooltip.
3. Score histogram: the "pass 80" label sat on top of the 80-89 bar's count. Label is now right-aligned to the left of the dashed line.
4. Overview "Needs human review": up to 3 reason chips wrapped onto a second line per call. Now two chips plus `+n`.
5. Wizard deep link: screenshots of step 5 and the summary need a stable URL, so `?step=` selects the step (selection already lives in `?agent=&s=&p=&l=`).
6. Verified, no change needed: score numbers always printed in cells; critical cells carry the corner triangle (shape, not colour only); verdicts are icon + word; Critical is the only solid badge; no gradients, shadows or emoji; dark mode keeps the same two colour uses.
