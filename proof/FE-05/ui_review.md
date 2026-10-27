# FE-05 UI self-review (light + dark; real-API screenshots in `screenshots/`, synthetic-data renders of 501-backed pages in `screenshots-synthetic/`)

1. DLQ: the error cell wrapped to two lines and made rows uneven. Now a single truncated mono line (full text in the title and the Sheet).
2. Dialect report: a lone "completed" status pill floated under the aside panels and meant nothing next to the title. Removed; progress is already in the eyebrow ("12 of 12 results").
3. Dialect heatmap: low-sample hatching first used a CSS gradient, which direction.md bans. Replaced by an SVG hatch pattern (shape, not colour, not a gradient) with a visible "low n" word.
4. Dialect scale: legend now lists steps worst to best with the direction stated ("Lower is better" / "Higher is better") and flips the colour mapping for entity accuracy.
5. Integrations, regression, calibration, dialect: every page whose endpoint answers 501 shows a plain "not enabled in this build" state naming the owner task instead of an error, with the page header and primary action still present (disabled with a reason).
6. API keys: the create dialog and the one-time reveal are one dialog; Esc and the backdrop do not close the reveal; `Done` stays disabled until "I have copied the key"; after closing, the key is gone from the DOM, storage and URL (tested).
7. Audits list: in-progress rows poll every 3 s; the Recording column shows the call id because `GET /calls` has no file name (gap G-10, noted in proof).
8. Verified, no change needed: no emoji, no gradient, no panel shadows; verdicts always icon + word; secrets are write-only everywhere ("Set" + Replace).
