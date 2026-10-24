# 10. Call detail  `/calls/[id]`

Requirements: FR-DB-3 (Must, never cut), FR-EV-7 human review (Should), FR-AU-3 speaker swap, FR-AU-5 promote (Should), FR-EV-6. Acceptance: clicking an evidence turn seeks the audio. Visual reference: `../mock-call-detail.html` (and `proof/DES-01/call-detail-*.png`). The mock is the source of truth for look; this spec adds behaviour and states.

Purpose: explain why one call failed, with the evidence one click from every claim. Works for simulated calls and uploaded or webhook-imported audits (same page; differences noted).

## Layout (desktop 1440)

```
EYEBROW  Call 17 of 40 | Synthetic caller | kn-en              [Copy link] [Promote to regression]
TITLE    Agent confirmed 40,000 when the caller said 4,000         (judge `summary`, sentence)
         supporting sentence
+- MetaStrip x6: Agent | Scenario | Persona | Line | Duration | Judge ------------------------+
+- left (fluid) ------------------------------------+ +- right (408) ---------------------------+
| Panel Audio: transport, ruler, lanes (Agent,       | | Panel Verdict: VerdictBadge + FlagChip, |
| Caller, Events, Latency), evidence band, playhead  | | overall score hero, Meter with pass     |
| Panel Transcript: filter segments, TranscriptTurns | | line, review reasons, [Override score]  |
|                                                    | | Panel Failure tags                      |
|                                                    | | Panel Dimension scores (7 rows)         |
|                                                    | | Panel Deterministic checks              |
|                                                    | | Panel Metrics (2 x 3 StatTiles)         |
+----------------------------------------------------+ +-----------------------------------------+
```
Under 1180px the right column stacks below the transcript, except the Verdict panel which moves above the Audio panel (compact: badge, flag, score, Meter) so the answer comes first on narrow screens.

## Regions and behaviour

**Header.** Title = evaluation `summary` rewritten as one sentence by the judge; if absent (not yet evaluated) title is "Call 17" with the StatusPill. Actions: `Copy link` (keeps `?turn=`), `Promote to regression` (primary, only for failed calls; for passed calls it is secondary and labelled `Add as regression test`).

**Audio panel.** wavesurfer.js drives a custom two-lane layout (speaker lanes from `caller` and `agent` tracks; `mixed` plays). Components: `AudioTransport` (play/pause 36px accent, clock mono, speed menu), lane labels, ruler every 10 s, `Events` lane (barge-in triangle, tool-call square, silence gaps over 2 s as a hatched bar), `Latency` lane (bar per agent turn at its start x, labelled, dashed 2.0 s target line, bars coloured by threshold), evidence band (translucent `--fail`, 1px edges, label "Evidence #4-6") for the evidence turns of the currently selected failure/dimension, playhead 2px accent with diamond head. Clicking anywhere on a lane seeks. Uploaded audits have a single mixed waveform with diarisation colour regions instead of two lanes; no Latency lane unless turn times exist.

**Transcript panel.** `TranscriptTurn` rows: time + index, speaker label with a coloured square (agent accent, caller khaki), text, translation line under non-English text (EN chip), caller ground truth vs "Agent heard" block for simulated calls when they differ (mono, differing words in `--fail-fg` weight 500), glass-box tool calls as a mono block, barge-in note, per-turn latency chip, TagChips for failure types attached to that turn. Evidence turns: 3px `--fail` left edge and tint. Playing turn: accent dot at the right and `--bg-selected`. Selected (from a link): 2px accent outline. Segmented filter: All, Evidence, Agent, Caller. The transcript auto-follows the playhead unless the user scrolled in the last 5 s (then a "Jump to current" pill appears). Click a turn seeks to its `start_ms`.

**Evidence references.** `#n` buttons appear in failure tags, dimension rows and checks. Click: seek, scroll, select, and set the evidence band to that item's turns. `?turn=4` in the URL does the same on load.

**Verdict panel.** `VerdictBadge` (pass, fail or critical), `FlagChip` for `needs_human_review` beside it, overall score as hero mono number with `/ 100`, `Meter` with the pass-line tick at 80, `review_reasons` as mono chips, `Override judge score` button (opens the human review Sheet).

**Failure tags.** `TagChip` per failure type with count, linking to its first evidence turn. Cross icon for tags tied to dimensions scored 0-1, triangle for 2.

**Dimension scores.** Seven `DimensionRow`s in weight order: name, weight %, `critical` badge when applicable, points `6.25 / 25`, `ScoreChip n/4`, `Pips`, reason (shown for scores of 2 or less; others expand with a chevron to read the reason), `EvidenceRef`s. Header aux shows "weighted sum 48.75".

**Deterministic checks.** Rows: icon (check, cross, triangle for warnings), mono `check_key`, detail, result word, `must pass` chip, evidence refs. Failed must-pass checks sort first.

**Metrics.** Six `StatTile`s: response p50, p95, first greeting, barge-in honoured, talk time split, turns; each with the target caption and threshold icon.

**Human review (Sheet 480px).** Reviewer name (prefilled), pass/fail switch, critical switch, seven dimension selectors 0-4 (segmented, defaulting to the judge's value shown as a ghost marker), notes. Footer: `Save review`. After saving, the Verdict panel shows "Human review by {name}: fail, critical" under the judge verdict; the judge value is never overwritten visually. Saved reviews feed Calibration.

**Promote dialog.** Fields from the API: failure type (select of the 14 types, preselected to the judge's first), status (`blocking`, `scheduled`, `manual`; default `blocking`), baseline score (number, default 80, helper "Future runs must score at least baseline minus tolerance 5"), notes. Footer `Promote to regression`; on success a Toast with links to the new scenario and the regression test.

**Uploaded audit specifics.** MetaStrip shows Source (upload, webhook), Language, Uploaded by; a `Speakers` panel under Audio with the diarisation mapping: "Speaker 1 = Agent, Speaker 2 = Caller" and a `Swap speakers` button (ConfirmDialog: re-evaluates; takes a minute). `Original` audio track selectable next to `Mixed`. Scenario-specific criteria replaced by agent-level goals, shown in the Scenario cell as "Agent goals".

## Components
`PageHeader`, `MetaStrip`, `Panel`, `Waveform`, `AudioTransport`, `TranscriptTurn`, `SegmentedControl`, `VerdictBadge`, `FlagChip`, `Meter`, `TagChip`, `EvidenceRef`, `DimensionRow` (`ScoreChip`, `Pips`), `CheckRow`, `StatTile`, `Sheet` (review), `Dialog` (promote, swap speakers), `Toast`.

## Data
`GET /calls/{id}` (turns, tool_calls, metrics, checks, evaluation), `GET /calls/{id}/audio/{track}` with Range, `POST /calls/{id}/review`, `POST /calls/{id}/promote`, `POST /calls/{id}/reevaluate`, `POST /calls/{id}/speaker-map`. Run item context (scenario/persona/line titles): from the call or via run items (gap G-9 if the call object lacks them).

## States
- **Loading:** header skeleton; MetaStrip skeleton cells; Audio panel shows a flat 80px skeleton with disabled transport; transcript 6 skeleton turns; right column panel skeletons. Audio loads independently: transcript becomes usable before audio, transport shows "Loading audio".
- **Call in progress** (simulated, status running): transcript streams in turn by turn (poll 2 s), Audio shows partial waveform growing and a `Live` pill, Verdict panel says "Not scored yet. Scoring starts when the call ends", dimension rows are skeletons.
- **Transcribing (upload):** Audio plays `original`; transcript EmptyState "Transcribing. This usually takes under a minute" with indeterminate bar; right column skeleton.
- **Evaluating (call ended, judge pending):** transcript and metrics visible, Verdict panel "Scoring in progress", deterministic checks may already show.
- **Judge error (`status` is `judge_error`):** `--fail-tint` strip in the Verdict panel "The judge did not return a valid result. Deterministic checks are shown below." + `Re-evaluate`. Overall score shows dash; verdict derives only from checks if they fail ("Failed must-pass check") otherwise "Not scored".
- **Low confidence:** `confidence: low` shows a neutral chip "Judge confidence low" and sets the FlagChip reason `judge_low_confidence`.
- **No evidence turns** for a dimension: the row says "No specific turn" and EvidenceRef area is hidden.
- **No audio** (recording failed or purged): Audio panel EmptyState "No recording for this call" + reason if known; transcript still works; seek disabled with tooltip.
- **Audio error (404/decode):** inline error in the Audio panel with Retry; transcript unaffected.
- **Error loading call:** 404 page error; 403 names the scope.
- **Human review conflict (409/already reviewed by this reviewer):** Sheet shows "You already reviewed this call. Update review?" and loads the old values.
- **Promote already done:** the button changes to `Regression test exists` (link) and is disabled.
- **PII:** transcript shows masked values as returned; no unmask control.
- **Keyboard:** Space play/pause, Left/Right 5 s, `j`/`k` turn, `[`/`]` evidence; shortcut hint in a Tooltip on the transport.
