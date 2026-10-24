# 12. Dialect  `/dialect`, `/dialect/[reportId]`

Requirements: FR-DB-4, FR-DI-1..4, FR-DI-6 (Must, never cut). Purpose: show which dialect and line-condition combinations the ASR gets wrong, with sample counts and uncertainty, and let the user drill down to the worst clips. This is the product's differentiator; the heatmap here must be README- and demo-ready.

## Layout `/dialect` (datasets and reports)

```
EYEBROW  2 datasets, 3 reports
TITLE    Dialect gap report                                    [New dataset]
+-- Panel: Datasets -------------------------------------------+ +-- Panel: Reports ----------+
| Kannada dialects v1   118 clips   consent ok   [Evaluate]     | | latest first, status, date  |
+--------------------------------------------------------------+ +----------------------------+
```
Dataset row: name, clip count, languages and dialect labels as chips, consent state. Row actions: `Upload clips`, `Evaluate`, `Open latest report`.

### Upload clips (Sheet 560px)
Step 1: download CSV template link (`file, reference_text, language, dialect_label, speaker_id, consent, domain_terms`). Step 2: manifest CSV `FileDropzone` and clips ZIP `FileDropzone`. Result view after upload: "Accepted 118. Rejected 2" with a rejection table (row, reason, e.g. "consent must be true") and `Download rejections`. Banner stays: "Clips without consent are never stored" (NFR-9).

### Evaluate (Dialog)
Condition checklist defaults to `clean_16k`, `pstn_8k_alaw`, `pstn_street_10db` (named after the noise profiles), engine list (`gnani-prisma`; a second engine is Could and appears only when installed). Shows "Expected 354 results" and cost note. `Start evaluation`.

## Report `/dialect/[reportId]`

```
EYEBROW  Kannada dialects v1 | gnani-prisma | 118 clips, 354 results   [Metric: WER | CER | Entity v] [Export HTML]
TITLE    North Karnataka speech on a street line has the worst entity accuracy: 71%
+-- Heatmap panel (dialect rows x condition columns) -------------+ +-- Detail aside (408) ----+
| cell: metric value, n, CI; click selects                        | | selected cell: value, n,  |
|                                                                 | | 95% CI, worst clips list  |
+-----------------------------------------------------------------+ | top errors, bias terms    |
+-- Panel: Top misrecognised words (ref -> hyp, count) -----------+ +---------------------------+
```
- Title is generated: worst cell of the selected metric ("{dialect} on {condition} has the worst {metric label}: {value}"), with sample size mentioned in the supporting sentence. If the worst cell has n below 10, the title is replaced by "Not enough clips to rank dialects yet" (honesty rule) and cells with low n are hatched.
- **Metric selector:** `SegmentedControl` WER, CER, Entity accuracy. For WER and CER lower is better, for entity accuracy higher is better; the colour scale is flipped accordingly so the same step colours mean good/bad in all three; the legend states direction ("lower is better").
- **Heatmap:** rows dialect labels (sorted by worst), columns conditions in fixed order clean, phone, noisy. Cell shows value in mono (WER as `31%`), small `n=24` beneath, 3px radius. Value to step mapping for WER: below 10% step 5, 10-19 step 4, 20-29 step 3, 30-44 step 2, 45+ step 1; CER and entity use their own documented thresholds in `dialectScale.ts` (FE) and shown in the legend. Thresholds are display choices, not product claims, and are stated under the legend.
- **Confidence:** each cell exposes the 95% CI in the tooltip and in the detail aside as a range bar; cells whose CI overlaps the CI of the best cell in their column carry no marker; cells where n is below 10 are hatched with a "low n" label (shape, not colour). This is the "speaker-grouped bootstrap" output (FR-DI-4).
- **Detail aside (selected cell):** metric value and CI range bar, n clips and speakers, secondary metrics (the other two), `Worst clips` list (up to 10): clip name, reference text snippet, hypothesis snippet, WER, a play button, and a diff view toggle; rows open a Dialog with full reference vs hypothesis word diff (added/removed shown with plus/minus icons and underline, not colour only) and the audio. Clips are only playable if consent is true (always, by ingest rule).
- **Top errors panel:** `ref -> hyp` pairs (Kannada/Devanagari text with `lang`), count, and `bias_suggestions` as chips with `Copy list` (for the agent's bias list).
- **Export HTML:** link to `/dialect-reports/{id}/html`.

## Components
`PageHeader`, `Panel`, `DataTable`, `Sheet`, `FileDropzone`, `Dialog`, `SegmentedControl`, `Heatmap` (dialect mode: n, CI, hatch), `RangeBar` (CI), `ClipRow` (play, diff), `WordDiff`, `ProgressBar`, `TagChip`-style term chips, `Button`.

## Data
`POST /dialect-datasets`, `POST /dialect-datasets/{id}/samples`, `POST /dialect-datasets/{id}/evaluate`, `GET /dialect-reports/{id}` (aggregates, top_errors, bias_suggestions, html, progress). Listing datasets and reports, and per-clip results for drill-down: gap G-11.

## States
- **Empty (no dataset):** "No dialect datasets yet. Upload consented native-speaker clips to see which dialects and phone conditions fail." Primary `New dataset`; link "What a good dataset looks like" (docs). Never shows sample charts.
- **Dataset with no clips:** card shows "0 clips" and `Upload clips` as primary.
- **Evaluating:** report page shows header, `ProgressBar` "212 of 354 results", heatmap with finished cells filled and others `--score-na` dashes; the page polls every 3 s; Export disabled.
- **Report complete with few clips:** low-n hatching and the honest title described above.
- **Loading:** heatmap skeleton at the expected grid size; aside skeleton.
- **Error:** upload rejections (above), evaluation failure strip with `Retry`, partial results ("14 results failed: STT error") with a link to list them, 404 report. Zero-consent upload (all rows rejected): clear error "No clips accepted. Every row needs consent = true."
- **Language fonts:** Kannada and Devanagari text must render with the embedded Noto fallbacks; any `tofu` square is a QA defect.
