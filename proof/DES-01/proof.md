# DES-01 proof (design direction, tokens, call-detail mock)

Status: done-unverified, for owner approval. Delivered in two passes: (1) research, direction, tokens, call-detail mock; (2) after PM-01 was merged (`docs/SCOPE.md`), per-page wireframe specs, component lists and empty/loading/error states for all 17 FR-DB-1 pages, and the verdict change below.

## What was built
| File | What |
|---|---|
| `docs/design/references.md` | 11 references with links, what to take and leave |
| `docs/design/direction.md` | chosen direction "Field Instrument": palette, type, spacing, radius, elevation, score scale, chart style, states, 5 rules, banned-list check |
| `docs/design/tokens.css` | CSS variables, light (`:root`) and dark (`.dark`, `[data-theme="dark"]`) |
| `docs/design/pages/00-shared.md` + `01..17-*.md` | shell, shared component catalogue, state patterns, a11y and responsive rules; one spec per FR-DB-1 page (wireframe, components, data, interactions, states); section 11 lists 13 API data gaps for TL |
| `docs/design/mock-call-detail.html` | single self-contained Call Detail mock (fonts embedded as base64, tokens inlined, no network needed), clearly labelled sample data |
| `proof/DES-01/validate_palette.py` + `.log` | WCAG contrast + colour-vision-deficiency validator for tokens.css |
| `proof/DES-01/check_specs.py` + `.log` | checks every FR-DB-1 page has a spec with Components, Data and empty/loading/error states |
| `proof/DES-01/build_mock.py`, `mock-template.html` | generator for the mock (waveform, ruler, derived numbers) |
| `proof/DES-01/screenshots.js`, `*.png` | Playwright renders |

## Reproduce
```
python3 -I proof/DES-01/validate_palette.py            # expect: RESULT: PASS (light + dark)
python3 -I proof/DES-01/check_specs.py                 # expect: RESULT: PASS (17 pages)
python3 -I proof/DES-01/build_mock.py                  # expect: wrote .../mock-call-detail.html; overall=48.75, p50=1.1, p95=2.6
PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node proof/DES-01/screenshots.js
   # expect 6 lines, each: horizontal-scroll=false console-errors=0
```
(`build_mock.py` downloads Geist, Geist Mono and Noto Sans Kannada from Google Fonts on first run; set `FONT_CACHE` to reuse a folder.)

## Real output
- `validate_palette.log`: all text pairs meet their WCAG target (body 17.0:1 light / 15.1:1 dark; muted 5.6:1 minimum; score-chip text 4.9:1 minimum); `--border-strong` 3.5:1 / 3.3:1; adjacent score steps and pass/warn/fail separated under protan, deutan, tritan simulation (Machado 2009) by deltaE >= 14 or L* difference >= 9.
- Screenshots (`proof/DES-01/`): `call-detail-light-1440.png`, `call-detail-dark-1440.png` (full page), `call-detail-light-fold.png`, `call-detail-dark-fold.png` (first screen at 1440x900), `call-detail-light-390.png`, `call-detail-dark-390.png` (phone width, no horizontal scroll).
- Interaction check (Playwright): clicking evidence ref `#6` moves the playhead to 01:00 and the theme toggle switches to dark. The mock plays no audio.
- Mock CSS contains no raw hex or rgb() values (only `var(--token)` and `color-mix` of tokens); checked by regex on the template.

## Honest limits
- Hamming, Cekura, Datadog, Sentry app screens are behind logins; they were judged from public docs/blogs (stated in references.md). Dribbble/Godly/Land-book/Mobbin were only used as "what to avoid" checks; no screenshots were copied.
- Sample content is invented and labelled. The overall score (48.75), per-dimension points, p50/p95 and talk-time percentages are computed by `build_mock.py` from the sample turns; the script asserts them.
- Verdict is 3-state (pass, fail, critical) per the rubric, as directed by the Orchestrator; `needs_human_review` is a separate FlagChip (direction.md 2.5). The earlier amber "Review" verdict was removed from direction.md and the mock.
- Kannada sample lines were written by the designer agent, not by a native speaker; they should be read by one before any public screenshot.
- The 5-step mapping of 0-100 to score bands, and the WER/CER/entity colour thresholds on the Dialect page, are display proposals; no contract is changed. Page specs assume 13 endpoints or fields that `06-api-spec.md` lacks (pages/00-shared.md section 11); not changed by design (contracts are frozen).

Commit: see `git log -1` on branch `task/DES-01` (SHA reported in the final message).
