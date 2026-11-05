# Design direction: bone and espresso

Status: in use (redesign, 4 Nov 2026). Replaces DES-01 "Field Instrument". Tokens: `docs/design/tokens.css`, a copy of `web/app/tokens.css` (the app reads the web copy; edit it there and re-copy). Research from DES-01 still applies: `docs/design/references.md`. The DES-01 mock (`docs/design/mock-call-detail.html`, screenshots in `proof/DES-01/`) shows the old look and is kept as history.

## 1. The look in one paragraph

Pareeksha is a measuring tool for voice agents, so it still looks like an instrument and not a marketing site. Light mode is warm bone paper with near-black ink; dark mode is a warm espresso black, not blue-black and not neutral grey. Type is Wix Madefor: Display for titles and figures, Text for everything you read. Geist Mono is kept only for things that are code: ids, failure codes, line names, commands. Colour appears in two places only: the five-step **score scale** and the verdict colours (both kept from DES-01), and one **sky-blue accent** for interaction. When something on screen is red or orange, it is a finding.

What this is not: a purple-blue gradient SaaS, a glow-on-black "AI" dashboard, or default shadcn grey. Banned list is in section 9.

## 2. Colour

All values live in `tokens.css`, written in OKLCH except the verdict colours and the light score scale, which keep the hex values DES-01 validated. Contrast and colour-vision checks: `python3 -I proof/DES-01/validate_palette.py` (reads hex and `oklch()`; result PASS for light and dark; output in `proof/REDESIGN/validate_palette.log`).

### 2.1 Neutrals (warm)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg-canvas` | bone, L 95.5 | espresso, L 14.5 | app background |
| `--bg-surface` | L 99.3 | L 18.5 | panels, tables, inputs |
| `--bg-sunken` | L 92.2 | L 12.5 | sidebar, wells, tracks |
| `--bg-hover` | L 93.6 | L 22.5 | row and button hover |
| `--bg-selected` | blue-tinted L 91.5 | blue-tinted L 26 | active nav, selected segment |
| `--border` | L 87.5 | L 26.5 | hairlines between and around panels |
| `--border-strong` | L 56 | L 52 | inputs and buttons (4.6:1 / 3.4:1 on surface) |
| `--fg` | L 21 | L 94.5 | text (17.4:1 / 15.9:1 on surface) |
| `--fg-muted` | L 41 | L 79 | secondary text (8.7:1 / 9.6:1) |
| `--fg-subtle` | L 46 | L 70 | captions, timestamps (7.0:1 / 7.0:1) |

Light neutrals sit at hue 75 (bone), dark at hue 60 (espresso), chroma 0.008 to 0.016.

### 2.2 Accent (interaction only)

`--accent` sky blue, `oklch(46% 0.13 242)` light and `oklch(77% 0.12 232)` dark, with `--accent-on` text at 6.6:1 and 9.4:1. Used for the primary button, links, focus ring, play button, playhead, active nav icon and selected segment. Never for data and never as a gradient. Blue was chosen because it collides with no score or verdict hue (red, orange, amber, teal).

### 2.3 Verdict colours (3 states)

Unchanged from DES-01 in hue and meaning. Always shown as **icon + word + colour**, never colour alone. Dark values are re-tuned so they sit on espresso instead of glowing on it.

| State | Meaning | Icon | Light solid / text / tint | Dark |
|---|---|---|---|---|
| Pass | `passed = true` | circle-check | `#0F7A63` / `#0A6551` / `#DAEEE6` | OKLCH, hue 170 |
| Fail | `passed = false` | circle-x | `#CF4A1C` / `#A63810` / `#F8DDD1` | OKLCH, hue 38 |
| Critical | `critical_failure = true` | octagon-x, solid fill | `#8E1D08` on white | deep red `oklch(48% 0.16 27)` with light text |

### 2.4 Score scale (the one data palette)

Five ordinal steps, worst to best, for score chips, pip bars, heatmap cells and histogram bars. The number is always printed on or next to the fill. Light values are DES-01's hex; dark values keep the same hues a step deeper.

| Step | Light fill / text | Dark fill | Dimension (0-4) | Overall (0-100) |
|---|---|---|---|---|
| `--score-1` | `#9E2A0A` / white | `oklch(52% 0.150 30)` | 0 | below 40 |
| `--score-2` | `#D9622B` / `#1F0C03` | `oklch(68% 0.130 52)` | 1 | 40-59 |
| `--score-3` | `#E9B03A` / `#2B1D00` | `oklch(80% 0.120 88)` | 2 | 60-79 |
| `--score-4` | `#5FB4A6` / `#062620` | `oklch(74% 0.080 180)` | 3 | 80-89 |
| `--score-5` | `#0B6F66` / white | `oklch(62% 0.090 185)` | 4 | 90-100 |
| `--score-na` | `#D4CFC1` / `#3D3A32` | `oklch(30% 0.012 65)` | not run | not run |

- **The pass line (80) sits between step 3 and step 4.** In bars and meters a 2px ink tick marks 80.
- Neighbouring steps stay at least 14 CIE76 deltaE apart under protanopia, deuteranopia and tritanopia, or 9 L* points apart (the validator checks both).
- Fills are never the only carrier of meaning: cells print the value, chips print `n/4`.

### 2.5 Verdict versus review flag

Unchanged: the verdict is 3-state (Pass, Fail, Critical). `needs_human_review` is a separate **flag**: an amber-tinted chip with a flag icon ("Needs human review"), placed beside the verdict.

### 2.6 Speakers and chart series

`--speaker-agent` is the accent blue; `--speaker-caller` warm sand. `--series-1..4` are blue, sand, violet and stone. Score hues are never reused for categories.

## 3. Typography

| Role | Font | Notes |
|---|---|---|
| Titles, figures | **Wix Madefor Display** 500 | self-hosted in `web/app/fonts/` (latin, latin-ext); tracking -0.022em |
| Body and UI | **Wix Madefor Text** 400/500/600 | self-hosted; `font-synthesis: none` |
| Ids, failure codes, line names, code | **Geist Mono** | `"tnum" 1, "zero" 1`; never for labels |
| Kannada and Devanagari | **Noto Sans Kannada / Devanagari** | fallbacks in `--font-sans`; line-height 1.75 for these scripts |

Figures that compare use `font-variant-numeric: tabular-nums` (the `.num` class) in the body face, not mono.

| Token | Size / LH | Use |
|---|---|---|
| `--text-2xs` | 12 / 16 | mono chips |
| `--text-xs` | 13 / 18 | captions, timestamps, badges |
| `--text-sm` | 14 / 20 | tables, labels, dense UI |
| `--text-base` | 16 / 24 | body, transcript |
| `--text-md` | 17 / 24 | panel titles |
| `--text-lg` | 20 / 28 | section titles, long page titles |
| `--text-xl` | 30 / 34 | page titles |
| `--text-2xl` | 46 / 48 | the one figure a page leads with |

Rules: sentence case everywhere; labels are the body face a step smaller, never uppercase or tracked; transcript text never below 16px.

## 4. Space, radius, elevation

- **Spacing:** 4px base, both the DES-01 names (`--space-0..16`) and the redesign scale (`--space-3xs..4xl`: 2, 4, 8, 12, 16, 24, 40, 64, 96, 144). Panel padding 20; gap between panels 24; page padding 40 (16 on phones). Table row 40, control height 36.
- **Radius, one per level:** 5 (chips, heatmap cells), 9 (inputs, menus), 14 (panels), 18 (dialogs), pill (buttons, segmented controls).
- **Elevation:** borders first. Panels have a 1px `--border` and no shadow. Only floating things (menus, toasts, dialogs, sheets) get `--shadow-float`.
- **Motion:** 120 ms for hover and press, 220 ms for panel changes, ease-out. Only `transform` and `opacity` animate. `prefers-reduced-motion` stops all of it, including the live run dot.

## 5. Chart and data-viz style

Unchanged from DES-01 except type: values use the body face with tabular figures instead of mono. Flat, thin, labelled; dashed and labelled threshold lines; direct labels over legends; the waveform keeps two speaker lanes on one shared time axis with a 2px accent playhead.

## 6. Components

Built in `web/components/ui/`: `Button` (pill, 36px, primary / secondary / ghost / destructive), `PageHeader` (title, then a muted context line, then the supporting sentence; no label above the title), `Panel` (one container recipe), `TileRow` + `StatTile` (a ruled tally between hairlines, not boxed tiles), `ScoreChip`, `VerdictBadge`, `FlagChip`, `TagChip`, `EvidenceRef`, `Meter`, `Pips`, `DataTable`, `FilterBar`, `Segmented`, `Switch`. Every control has hover, active, focus-visible and disabled states; the focus ring is a 2px `--focus-ring` outline, instant.

Empty, loading and error states are as `pages/00-shared.md` section 5 specifies.

## 7. Layout

- Fixed left sidebar, 248px, grouped Build, Evaluate, Operate, with one Lucide icon per destination; under 861px it becomes a sheet. The wordmark links to the product page at `/welcome`, which has its own chrome.
- Top bar 56px: the current section and the theme toggle.
- Page = title (a finding where there is one: "18 of 18 calls failed, 12 critical"), context line, supporting sentence, then the content. Lists are one panel holding a filter bar and a table; detail pages put the evidence left and the verdict right (380px), stacking under 1180px.

## 8. Five rules that make it feel like Pareeksha

1. **Colour is a measurement.** Only score and verdict colours and the single accent carry chroma.
2. **Lead with the finding, then the number.**
3. **Everything has evidence one click away.** Any score, tag or check links to the turn that caused it.
4. **One shared time axis** for waveform, events and latency.
5. **Quiet chrome, readable content.** Hairlines instead of shadows; 16px body; whitespace between panels, not inside tables.

## 9. Banned

Purple-blue or any decorative gradient; emoji as icons; glow, glass or coloured shadows on app screens; identical card grids; uppercase tracked labels; mono used as decoration; invented numbers; untouched default shadcn.

## 10. Handing over

- Edit tokens in `web/app/tokens.css`, re-copy to `docs/design/tokens.css`, and re-run the validator.
- `web/app/globals.css` maps tokens to Tailwind utilities (`bg-canvas`, `text-muted`, ...) in `@theme inline`; components never hard-code colours.
- Page specs in `docs/design/pages/` still describe structure and states; where they mention 13px tables, eyebrow labels or mono numbers, this document wins.
