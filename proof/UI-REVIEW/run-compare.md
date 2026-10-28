# UI review: Run compare (FE-03b) — PASS

Independent review of proof/FE-03b/screenshots/compare-{light,dark}.png (real data, 4 regressions) against docs/design/direction.md and docs/design/pages/09-run-compare.md, SHA f857c34.

Pass: warm paper/near-black surfaces, hairlines, mono tabular numbers; colour only on score scale and cobalt links; verdict never colour-only (icon + word + signed number + "worse" in words); newly-failing cells use a 2 px outline plus a legend; regressions listed first; both themes consistent; layout matches the spec.

Fixes (non-blocking, <=8):
1. Heatmap delta overlay (-36/-65, 10 px) is hard to read on score-1 fills in light mode; raise size to 11-12 px or add a light chip.
2. Legend swatch for "unchanged" is teal, which reads as a high score; use a neutral muted swatch.
3. Delta bar (64 px) is mostly empty track for large deltas and the left-fill orange is the score-2 hue; scale to max |delta| in table.
4. Run pickers are native selects; spec says searchable RunSelect combobox.
5. Dead space under the heatmap on the left while the right column continues; balance the two columns.
6. "Base call"/"Head call" repeated per row as identical link text; add row context in aria-label.
7. Latency p95 tile "not measured" occupies a full tile; consider a smaller muted treatment.
8. Dimensions "0.00" no-change row uses a dash glyph plus 0.00; keep one.
