# UI review vs docs/design/direction.md (verifier, 2026-10-27, RC b26ff54)
Screens: proof/QA-04/screenshots/*.png (real stack data, builder-captured; 186 mock Playwright tests re-run green by verifier). Light theme only was supplied; dark not reviewed.
Overall: tokens, hairline panels, mono numerals, verdict icon+word+colour are followed. Result: 13 PASS, 4 FAIL (Overview, Run detail, Run compare, Dialect).

| Page | Result |
|---|---|
| Overview | FAIL |
| Agents | PASS |
| Scenarios | PASS |
| Personas | PASS |
| Noise profiles | PASS |
| Runs | PASS |
| New run | PASS |
| Run detail | FAIL |
| Call detail | PASS |
| Run compare | FAIL |
| Audits | PASS (empty state only) |
| Dialect | FAIL |
| Regression | PASS (empty state only) |
| Integrations | PASS (empty state only) |
| DLQ | PASS (empty state only) |
| Calibration | PASS (empty state only) |
| API keys | PASS |

## Overview: FAIL
1. "No runs yet" hero/Worst calls/Recent runs contradict the populated "Needs human review" list; scope the list to the selected agent or say why it differs.
2. Agent switcher defaults to a `[bug:false_waiver]` agent; default to the agent with the latest run.
3. Sidebar panel ends at 720px in the tall capture while content continues (sidebar not sticky/full height).
4. Four stat tiles show "-" with no hero number; direction asks one hero number per screen, use it for pass rate when a run exists.
5. "Credits used ₹0 of ₹5,000" meter track is invisible at 0; draw the track.
6. Empty Worst-calls panel is taller than Platform health; align panel heights.

## Agents / Scenarios / Personas / Noise profiles: PASS
Fixes (minor): Agents "Connection: never tested" for all rows is noise, show a single test-all action; Scenarios "Used in" is "-" everywhere (API gap G-5); Personas voice column lacks play-sample; Noise profiles name column should wrap less at 1280px and the Rate cell "16 kHz" wraps onto two lines.

## Runs / New run: PASS
Runs: "Compare" disabled with no hint why (add tooltip "select two runs"); When column wraps to three lines ("10 minutes ago"), widen it. New run: summary "0 × 0 × 0 × 1" with a 40px "0 calls" is fine but "Create run" disabled state has low contrast; step rail does not show completion state.

## Run detail: FAIL
1. Score distribution histogram draws no bars for 2 calls (41.25 and 95); bars missing, only axis.
2. "Top failure types: No failure tags" while the calls table shows `missing_disclosure +2`; aggregate tags from calls.
3. Latency P50/P95 and Barge-in tiles show "-" for a finished run; show "not measured" with reason.
4. Matrix with one cell renders a full-width block; cap cell width.
5. Calls table scenario/persona cells wrap into two lines; widen columns.
6. Title "2 of 2 calls failed, 1 critical" contradicts the table (one call is Pass 95); recompute from verdicts.
7. Flag column shows only an icon button without label.

## Call detail: PASS
Evidence-seek, waveform regions, verdict, dimensions, checks and metrics match the DES-01 mock. Fixes: transcript is much shorter than the right column (leave white space; make audio sticky); "Read reason" collapsed for 3/4 and 4/4 dimensions hides evidence; turn #0 text "this call is being" is the STT/TTS cut (real defect in the greeting audio, not UI); latency bar labels (7.1/5.1) overlap target line; Metrics tiles use red X on values without stating the target in the same line.

## Run compare: FAIL
Page body is "This page is not implemented yet." (STUB(FE-03)): a nav item pointing at a placeholder. Build it, or remove from the sidebar with a written cut approval in CHANGELOG.

## Dialect: FAIL
Only the empty state exists; the heatmap with metric selector, n and CI cells has never been shown with data in any screenshot (needs H-02 clips or a synthetic report). Add a populated screenshot; label synthetic groups.

## Audits / Regression / Integrations / DLQ / Calibration: PASS (empty states only)
Empty states are conformant (icon, one primary action, plain sentence). Each still needs a populated real-data screenshot (audit rows, regression suite verdict, delivery log, a DLQ row with replay, kappa tiles). Calibration: reference to "gap G-13" is internal jargon in user copy; Integrations lists "Planned" connectors (Salesforce..., Slack) which advertises unbuilt features; DLQ "Replay all open" disabled with no tooltip; Regression headline "No suite run yet" duplicates the card title.

## API keys: PASS
Fixes: admin scope shown with a warning icon but no explanation; "How to use" block should include the CLI `apply` line; Last used "just now" for demo key is the web BFF, label it.
