# FE-04 proof: Call detail (transcript, audio timeline, scores, failure tags, review, promote)

Branch `task/FE-04` from `task/FE-03`. Commit: last commit of `task/FE-04`.

## Built
- `/calls/[id]` (`web/components/calls/`): header sentence from the judge summary, MetaStrip (agent, scenario, persona, line from the run items, duration, judge), Audio panel, Transcript, Verdict, Failure tags, Dimension scores, Deterministic checks, Metrics. Visual reference `docs/design/mock-call-detail.html`.
- **Audio**: one `<audio>` streams `GET /calls/{id}/audio/mixed` with Range; the waveform is drawn in SVG from the caller and agent tracks (one stroke per 100 ms, two lanes), ruler, Events lane (barge-in, tool calls, silence over 2 s), Latency lane with the 2.0 s target, evidence band, playhead with diamond head. Click any lane to seek. Play/pause, speed 0.75-1.5x. Waveform loads independently of playback; its error has Retry; no recording shows an empty state and the transcript still works.
- **Evidence refs** (`#n`) in tags, dimension rows and checks seek the audio, scroll and select the turn and draw the evidence band; `?turn=4` does the same on load. Keyboard: Space, Left/Right 5 s, `j`/`k` turns, `[`/`]` evidence.
- **Transcript**: All / Evidence / Agent / Caller filter, `lang` on Kannada and Hindi, "Agent STT heard" block with differing words in fail colour (caller ground truth vs heard), tool-call block, barge-in note, per-turn latency chip, tag chips, auto-follow with "Jump to current" after a manual scroll.
- **Verdict**: VerdictBadge, FlagChip, hero score, Meter with the pass line, review reasons, `Override judge score` Sheet (reviewer, pass/critical switches, seven 0-4 selectors showing the judge value, notes; `POST /calls/{id}/review`), judge-error strip with Re-evaluate, low-confidence chip. **Promote dialog** (`POST /calls/{id}/promote`, failure type, status, baseline, notes).
- **Uploads**: single mixed lane with diarisation regions, Speakers panel with Swap, latency not shown (recordings have none).
- `STUB(FE-04)`: the call route had none; the placeholder-free page replaces nothing else.

## Real data
Same stack and run as FE-03 (12 calls: Gnani TTS, line simulation, Gnani STT, DeepSeek judge). The upload-source call (`ravi_call_0412.wav`, Hindi) was produced by `proof/FE-04/real_calls.py audit`: a two-speaker TTS clip, real Gnani batch STT with diarisation, DeepSeek judge, stored with `source='upload'` and a speaker map, because `POST /audits` is still a 501 stub (EVAL-04). Spend in `../FE-03/credit_use.md` (the audit clip adds 1 diarised STT call of 26 s and 1 judge call).

## Not built / limits (said plainly)
- Review and promote call endpoints (`/calls/{id}/review`, `/promote`, `/reevaluate`, `/speaker-map`) are API-05/EVAL-04 stubs returning 501; the UI is built to the frozen contract and shows "not available in this build yet" instead of failing silently. Not exercised against real data.
- The API gives failure tags per call, not per turn. Tags are attached to the turns of the judge's dimension evidence (check evidence as fallback); mapping table in `web/lib/api/calls.ts`.
- No translation line under Kannada/Hindi turns (the API has no translation field); no "blind" labelling mode (calibration page is a stub, API-05).
- The waveform decodes the per-speaker tracks fully in the browser (small files); playback itself streams.

## Reproduce
Stack and data as `proof/FE-03/proof.md`, then:
```
python proof/FE-04/real_calls.py audit <agent id>      # (inside the backend image, see its docstring)
cd web && node scripts/shots.mjs ../proof/FE-04/screenshots "/calls/<id>?turn=2=call-critical-kn" "/calls/<audit id>=call-audit-upload"
node scripts/axe-real.mjs ../proof/FE-04/axe_real.json "/calls/<id>" "/calls/<audit id>"
npm run lint && npm run typecheck && npm run build && npx playwright test
```

## Results
- `lint.log` 0; `typecheck.log` 0; `build.log` OK; `gen-api-check.log` up to date.
- `playwright.log`: **167 passed, 0 failed, 0 skipped** (everything from FE-02 and FE-03 plus 6 call-detail tests: verdict and critical state, evidence ref seeks a Range-served audio element past 8 s and selects the turn, `k` moves a turn, `?turn=` opens seeked, 501 explained in the review Sheet, judge-error strip, no-recording state, upload mode with Speakers and no invented latency; axe wcag2a/aa on the mocked call page).
- `axe_real.json`: axe on the real call pages (critical Kannada call, pass call, uploaded audit), light and dark: **0 violations**.
- `screenshots/`: call-critical-kn, call-audit-upload, call-pass, each light and dark. `ui_review.md`: the self-review.
