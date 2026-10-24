# Design direction: "Field Instrument"

Status: proposed for owner approval (DES-01). Tokens: `docs/design/tokens.css`. Key-screen mock: `docs/design/mock-call-detail.html` (screenshots in `proof/DES-01/`). Research: `docs/design/references.md`.

## 1. The look in one paragraph

Pareeksha is a measuring tool for voice agents, so it should look like a good measuring instrument and not like a marketing site: warm paper-coloured surfaces, near-black ink, hairline rules, small radii, numbers set in a monospace with tabular figures. The page is calm and monochrome on purpose. Colour appears in only two places: the five-step **score scale** (which means "how well did this go") and one cobalt **interaction accent** (links, focus, play button, playhead). When something on screen is red or orange, the reader can trust that it is a finding. Dark mode is the same instrument with the lights off: warm near-black, not blue-black, same two uses of colour.

Built on: Linear's layered-surface discipline and hairlines (ref 1), Vercel Geist's ten-step neutral structure and type (refs 2, 3), Datadog's shared-time-axis trace view (ref 4) and PostHog's click-an-event-to-seek replay (ref 5) for the call screen, Sentry's issue-first failure framing (ref 6), and Okabe-Ito/Tol colour-vision-safe colour (ref 11). See `references.md` for links.

What this is not: a purple-blue gradient SaaS, a glow-on-black "AI" dashboard, or default shadcn grey. Banned list is in section 9.

## 2. Colour

All values live in `tokens.css`. Contrast and colour-vision checks run with `python3 -I proof/DES-01/validate_palette.py` (result: PASS for light and dark; output in `proof/DES-01/validate_palette.log`).

### 2.1 Neutrals (warm)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg-canvas` | `#F5F3ED` | `#0D0D0B` | app background |
| `--bg-surface` | `#FCFBF8` | `#151512` | panels, tables, inputs |
| `--bg-sunken` | `#EEEBE3` | `#0A0A08` | wells: code, waveform track, meter track |
| `--bg-hover` | `#F0EDE5` | `#1C1C18` | row / button hover |
| `--bg-selected` | `#E7E3D8` | `#26251F` | active nav, selected segment |
| `--border` | `#E1DCCF` | `#2B2A24` | hairlines between and around panels |
| `--border-strong` | `#8C8676` | `#6C695E` | inputs and buttons (3.5:1 / 3.3:1 on surface) |
| `--fg` | `#1A1915` | `#ECE9E0` | text (17.0:1 / 15.1:1 on surface) |
| `--fg-muted` | `#55524A` | `#ABA79B` | secondary text (7.5:1 / 7.6:1) |
| `--fg-subtle` | `#69655A` | `#928E82` | captions, timestamps (5.6:1 / 5.6:1) |

### 2.2 Accent (interaction only)

`--accent` `#2748B5` light, `#6F88F0` dark. Used for: primary button, links, focus ring, play button, playhead, selected-turn outline. Never for data and never as a gradient. It is a plain cobalt, deliberately not the lavender-blue of Linear or any purple.

### 2.3 Verdict colours (3 states)

Always shown as **icon + word + colour**, never colour alone.

| State | Meaning | Icon | Light solid / text / tint | Dark solid / text / tint |
|---|---|---|---|---|
| Pass | `passed = true` | circle-check | `#0F7A63` / `#0A6551` / `#DAEEE6` | `#3BB89D` / `#62D4BA` / `#0E2B25` |
| Fail | `passed = false` | circle-x | `#CF4A1C` / `#A63810` / `#F8DDD1` | `#EC6C40` / `#FF9670` / `#351A0F` |
| Critical | `critical_failure = true` | octagon-x, solid fill | `#8E1D08` on white | `#FF6F47` on `#260A02` |

Hues follow the Okabe-Ito triple (bluish green, orange-yellow, vermillion) because those stay separable for red-green colour blindness. Critical is the only solid-filled badge in the product, so it reads as heavier than Fail without needing a fourth hue.

### 2.4 Score scale (the one data palette)

Five ordinal steps, worst to best. Used for score chips, pip bars, heatmap cells, histogram bars. The number is always printed on or next to the fill.

| Step | Light fill / text on it | Dark fill / text on it | Dimension score (0-4) | Overall score (0-100) |
|---|---|---|---|---|
| `--score-1` | `#9E2A0A` / white | `#E5583A` / `#1F0602` | 0 | below 40 |
| `--score-2` | `#D9622B` / `#1F0C03` | `#F0954F` / `#231003` | 1 | 40-59 |
| `--score-3` | `#E9B03A` / `#2B1D00` | `#EFC95A` / `#261B00` | 2 | 60-79 |
| `--score-4` | `#5FB4A6` / `#062620` | `#66C2B2` / `#04211C` | 3 | 80-89 |
| `--score-5` | `#0B6F66` / white | `#1F9A8E` / `#03211D` | 4 | 90-100 |
| `--score-na` | `#D4CFC1` / `#3D3A32` | `#3B392F` / `#D9D5C8` | not run | not run |

Design notes:
- The scale runs deep red-brown, orange, amber, light teal, deep teal. Teal rather than green for "good" because teal separates from amber and orange for protan and deutan viewers; to a typical viewer it still reads as green-ish.
- Neighbouring steps differ by at least 14 CIE76 deltaE under protanopia, deuteranopia and tritanopia, or by at least 9 L* points (greyscale-safe). Numbers from the validator are in the proof log.
- **The pass line (80) sits between step 3 and step 4.** The first teal step therefore means "passes". In bars and meters a 2px ink tick marks 80.
- Dimension scores map 1:1 to the rubric anchors in `08-evaluation-rubric.md` (4 correct, 3 minor friction, 2 noticeable problem, 1 clear failure, 0 severe).
- Fills must not be the only carrier of meaning. Heatmap cells print the value; chips print `n/4`; pip bars sit next to the number.


### 2.5 Verdict versus review flag (decided)

Resolved by the Orchestrator (after PM-01): the verdict stays **3-state per the rubric: Pass, Fail, Critical**. `needs_human_review` is a separate **flag**, never a verdict. It is drawn as a neutral outlined chip with a flag icon and the label "Needs human review" (reasons listed as mono chips beside it), placed next to the verdict badge. Amber (`--warn`) remains for threshold warnings on individual metrics and checks (for example p50 latency 1.1 s against a 1.0 s target), for the flag icon, and for score step 3.

### 2.6 Speakers and chart series

`--speaker-agent` cobalt (`#2748B5` / `#8CA0F7`), `--speaker-caller` warm khaki-brown (`#7A6A4C` / `#C2AE86`). `--series-1..4` are cobalt, khaki, steel blue and stone grey. Score hues are never reused for categories.

## 3. Typography

| Role | Font | Notes |
|---|---|---|
| UI and body | **Geist** (Google Fonts, variable, OFL) | quiet geometric sans; weights 400/500/600 only |
| Numbers, timestamps, ids, tags, code | **Geist Mono** (Google Fonts, variable, OFL) | `font-feature-settings: "tnum" 1, "zero" 1` |
| Kannada transcript text | **Noto Sans Kannada** (Google Fonts) | Geist has no Kannada glyphs; line-height 1.75 for this script |
| Devanagari transcript text | **Noto Sans Devanagari** (Google Fonts) | same reason |

`--font-sans` already lists the fallbacks in this order. In Next.js use `next/font/google` with `subsets: ['latin']` for Geist and Geist Mono and the `kannada` / `devanagari` subsets for the Noto fonts, so the page does not ship scripts it does not show. Verified in the mock: Kannada and mixed Kannada-English lines render correctly with these fonts.

Scale (px / line-height). Dense by default because this is a work tool.

| Token | Size / LH | Weight | Use |
|---|---|---|---|
| `--text-2xs` | 11 / 14 | 500, uppercase, +0.06em | eyebrow labels, panel sub-labels |
| `--text-xs` | 12 / 16 | 400-500 | captions, timestamps, badges, chips |
| `--text-sm` | 13 / 20 | 400-500 | tables, dimension rows, secondary UI |
| `--text-base` | 14 / 22 | 400 | body, transcript, form text |
| `--text-md` | 16 / 24 | 500-600 | panel titles, clock |
| `--text-lg` | 20 / 28 | 500-600 | section titles, stat values |
| `--text-xl` | 26 / 32 | 600, -0.022em | page titles |
| `--text-2xl` | 40 / 44 | 600, -0.022em, mono | hero number (overall score, pass rate) |

Rules: sentence case everywhere; no bold paragraphs; one hero number per screen; transcript text never below 14px.

## 4. Space, radius, elevation

- **Spacing:** 4px base. `--space-1..16` = 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 (plus a 2px `--space-0`). Panel padding 16; gap between panels 24; page padding 32 (16 on phones). Table row 36, control height 32.
- **Radius:** 3 (badges, chips, heatmap cells), 5 (buttons, inputs), 8 (panels), 12 (dialogs). No pill-shaped cards. Pills (999) only for the score meter track.
- **Elevation:** borders first. Panels have **no shadow**; they are separated by a 1px `--border` and a one-step surface difference. Only floating things (popovers, menus, toasts, dialogs) get `--shadow-float`, which is translucent so it blends with the background (Geist guidance). No glow, no coloured shadows, no inner shadows.
- **Motion:** 120 ms for hover, 200 ms for panel changes, `cubic-bezier(.2,.7,.2,1)`. Respect `prefers-reduced-motion`. No decorative animation; the only moving thing on call detail is the playhead.

## 5. Chart and data-viz style

Style rules for every chart FE builds:

- **Flat, thin, labelled.** 1.5px lines, 2px radius bars, no gradients, no drop shadows, no 3D, no donut charts. Gridlines are `--grid` (same as `--border`), horizontal only.
- **Direct labels over legends** where there are one or two series. Values in Geist Mono.
- **Threshold lines are dashed and labelled** ("2.0 s target", "pass 80"). Bars past a threshold take the warning or fail colour; bars within it stay `--series-1`/steel.
- **Waveform** (call detail): two stacked lanes, caller and agent, one vertical stroke per 100 ms, 1.6px, with the speaker colour. Speech regions are drawn at full amplitude; silence is a flat noise-floor line, not blank. Failure evidence is a translucent `--fail` band across all lanes with a 1px edge, labelled "Evidence #4-6". Playhead is a 2px accent line with a diamond head. No gradient fills, no rounded "pill" bars.
- **Heatmap** (run matrix, dialect x condition): square-ish cells with 3px radius and 2px gaps, fill from the score scale, value printed in the cell in mono, row and column headers in `--fg-muted`. Empty cells use `--score-na` with a dash. A thin ink tick on the legend marks the pass line. Sort rows worst-first by default.
- **Distribution** (score histogram): 10-point bins, bars coloured by the five-step band they fall in, pass line as a vertical dashed rule.
- **Latency per turn**: bars on the same time axis as the waveform (Datadog pattern), dashed target line.

## 6. Components and states (how shadcn is bent to this)

shadcn/ui stays as the behaviour layer (Radix primitives, accessibility), but FE must not ship it untouched. Map its variables to our tokens in `globals.css`:

| shadcn variable | Pareeksha token |
|---|---|
| `--background` | `--bg-canvas` |
| `--card`, `--popover` | `--bg-surface` |
| `--muted` | `--bg-sunken` |
| `--accent` (shadcn hover fill) | `--bg-hover` |
| `--primary` / `--primary-foreground` | `--accent` / `--accent-on` |
| `--border`, `--input` | `--border` / `--border-strong` |
| `--ring` | `--focus-ring` |
| `--destructive` | `--fail` |
| `--radius` | `--radius-sm` (5px); cards use `--radius-md` |

Overrides FE should make on first pass: no card shadows; 32px control height; 13px table text; Geist; a `Badge` variant set of `pass | fail | critical | neutral` (verdicts) plus a separate `FlagChip` for `needs_human_review`; a `ScoreChip` (step colour, `n/4` or number); a `Pips` bar; a `TagChip` (mono failure tag, icon + label, optional turn reference); `EvidenceRef` (mono `#4`, seeks audio); `Meter` with pass-line tick; `Heatmap`; `Waveform` (wavesurfer.js regions styled per section 5).

Icons: `lucide-react` (already in the TRD), stroke 1.6, 16px (14px in dense rows). The mock draws the same shapes by hand; use lucide names `circle-check`, `circle-x`, `triangle-alert`, `octagon-x`, `flag`, `play`, `link`, `scale`.

Empty / loading / error states (all pages) are specified in `pages/00-shared.md` section 5; summary:
- **Empty:** one line saying what this page will hold and the single next action as a primary button, plus a muted one-line explanation. A small monochrome line illustration is allowed; no stock art. Example: "No runs yet. A run sends synthetic callers to your agent. Create a run."
- **Loading:** skeletons shaped like the final content (`--bg-sunken` blocks, no shimmer sweep, a 1.2 s opacity pulse that stops under reduced motion). Live run: rows appear in place; new rows flash `--accent-tint` once for 800 ms.
- **Error:** inline in the panel, `--fail-tint` strip with icon, one-line cause, a retry button, and the request id in mono. Never a full-page error for a single failed panel.
- **Partial / not applicable:** `--score-na` with a dash, tooltip explains why ("check skipped: no tool calls").

## 7. Information architecture and layout (summary; page-by-page specs come next)

- Left sidebar, 232px, grouped **Build** (Agents, Scenarios, Personas, Noise profiles), **Evaluate** (Runs, Audits, Dialect, Regression), **Operate** (Integrations, DLQ, Calibration, API keys), Overview on top. All 17 pages in FR-DB-1 are reachable from it; New run wizard, Run detail, Run compare and Call detail are reached from Runs.
- Top bar 48px: breadcrumb, environment/sample badges, theme toggle. No global search in v1.
- Page = title block (eyebrow, one-sentence finding as the title, supporting sentence), meta strip, then a two-column body (content left, verdict and findings right, 408px). Under 1180px it stacks; under 860px the sidebar collapses.
- Every finding is a link to its evidence. Evidence references are mono `#n` buttons that seek audio and scroll the transcript.

## 8. Five rules that make it feel like Pareeksha

1. **Colour is a measurement.** Only score and verdict colours and the single accent carry chroma. If something is coloured, it means "this scored X". Decorative colour is a bug.
2. **Lead with the finding, then the number.** Page titles are sentences ("Agent confirmed 40,000 when the caller said 4,000"), not nouns ("Call detail"). The hero number sits beside it, in mono.
3. **Everything has evidence one click away.** Any score, tag or check shows the turn that caused it (`#4`), and clicking it moves the audio and the transcript together.
4. **One shared time axis.** Waveform, speakers, events and latency align on the same x; the transcript scrolls with it. Time is always `mm:ss` in mono.
5. **Quiet chrome, dense content.** Hairlines instead of shadows, 13-14px text, tight rows, small radii. Whitespace is spent between panels, not inside tables.

## 9. Banned (checked against the mock)

| Banned | Status in the mock |
|---|---|
| Purple-blue gradients, any gradient fill | none; one flat cobalt accent |
| Emoji as icons | none; hand-drawn 1.6px stroke SVG icons, shape differs per state (check, triangle, cross, octagon) |
| Glowing cards, glassmorphism | none; no blur, no glow; shadow only on floating layers (none on this screen) |
| Identical card grids | none; the screen mixes a player, a log, a verdict, a stack of rows and a 2x3 stat grid with different structure |
| Lorem ipsum / unlabelled fake numbers | sample content only, labelled "Sample data" in the top bar and footer; derived values are computed by the build script from the sample turns |
| Untouched default shadcn | tokens replace every shadcn variable (section 6) |

## 10. Handing over

- FE-01/FE-02: import `tokens.css` once in `app/globals.css`; set `class="dark"` through `next-themes` (`defaultTheme: "system"`); do not hard-code colours in components.
- FE-04 (call detail): `mock-call-detail.html` is the visual reference; its CSS uses tokens only. Text and structure are sample.
- Page specs for all 17 FR-DB-1 pages, shared components and states: `docs/design/pages/` (start with `00-shared.md`). Checked by `proof/DES-01/check_specs.py`.
