# DOC-03-REC: recorded product demo (branch task/DOC-03-REC, from origin/task/EVAL-08)

`demo.mp4`: 63 s, 1920x1080, H.264, 30 fps, 2.6 MB (AAC audio track: silent except the call's own audio, turn 6 onwards, in shot 2).
`demo_poster.png`: frame at 14 s. Raw clips: `clips/*.webm` (14 MB, 1920x1080, 25 fps Playwright recordings, one per shot) and `clips/timings.json`.
Scripts: `scripts/demo/prerun.py` (planted-bug run + clean run), `dialect_load.py` (Vaani subset), `hubspot_live.py` (HubSpot integration + signed webhook), `record_demo.py` (Playwright, real clicks on http://localhost:3000), `edit_demo.py` (ffmpeg cuts, captions). Every cut: `cuts.json` (and the table below). No voiceover, no music.

Stack: Compose with `--profile workers` + the proxy overlay (base images pulled via mirror.gcr.io because Docker Hub returned 429), real Gnani STT/TTS and DeepSeek judge, SIMULATOR_REPLICAS=1.

## Data (what is real, what is synthetic)
| Item | Id | Real / synthetic |
|---|---|---|
| Failing run, mock agent `MOCK_BUGS=no_amount_confirm`, "Promise to pay on Friday" x "Manju — auto driver" x `pstn_8k_alaw` | run `49bef505-3a05-4100-9d24-0b812fd43051`, call `0c422c61-77c3-57a2-9670-007c968c37e7` | real calls (Gnani speech, DeepSeek caller and judge); score 71.25, **fail, not critical** (intent_miss, asr_misrecognition, tool_selection; evidence turns 3, 4, 6) |
| Same cell, clean agent | run `8ea6cbd4-715e-4cd9-998f-4b0e91827665`, call `e1b85e63-13a8-53d3-8429-b6ab5d43ed14` | real; 95.0, pass |
| Promote to regression | done on camera on call `0c422c61` (real click, real API write) | real |
| Dialect report `3b5f0df0-c2dc-430d-8830-d008c8db0a91` | dataset `b4cdc718-1ff4-4484-9cb2-1940954e4556` | real Gnani Prisma STT on a **subset**: 20 Vaani clips (4 per group, CC-BY-4.0, dataset-level consent) x 2 conditions (clean_16k, pstn_8k_alaw) = 40 results. n=4 per cell, all cells hatched "low", the page itself says "Not enough clips to rank dialects yet" |
| Audit uploaded on camera | call `69a2c970-c71d-4a63-9825-3278ae37c71c` | recording `demo_call.wav` is **synthetic** (two Gnani TTS voices, hi-IN, 13.7 s, stereo: agent left, caller right, "stereo channels are speakers" ticked); audit real: 48.75, critical (wrong_fact: 4,000 vs 4,500; missing_disclosure) |
| HubSpot: signed webhook delivery of the same recording with `metadata.phone=+919999900077` | call `69c256d6-8fe9-46b6-b931-16e77826d0e0`, integration `6981fe2e-8024-4937-be24-37eb5f1c4787`, note `415570741977` | real HubSpot API, **synthetic** contact "Pareeksha DemoSynthetic" (id 584973108949, +919999900077). Note created 25.1 s after the POST; body in `note_fetched.json` |
| GitHub | PR #3; red `pareeksha-regression` run 41097075186 on commit a8f8444; green run 41102511599 on b8b121e | real public pages |

## Shots and cuts (`cuts.json` has exact numbers)
| Out time (s) | Clip, source range, speed | On screen |
|---|---|---|
| 0 to 7.5 | 01_runs 1.5-15.0 s, 1.8x ("sped up") | Runs, open the failing run, matrix cell, click the cell |
| 7.5 to 19 | 02_call 8.0-19.5 s, 1.0x | Evidence 3 filter, click turn #6 (waveform seeks to 00:42), Play; the call's real audio (mixed recording, from 42.0 s) is mixed in at 13.1 s |
| 19 to 25 | 03_promote 5-17 s, 2.0x ("sped up") | Promote to regression dialog, confirm, Regression page |
| 25 to 32 | 04_compare 6-22 s, 2.3x ("sped up") | Compare bug run vs clean run: 0% to 100% pass, 71.25 to 95 |
| 32 to 38 | 05_dialect 3-15 s, 2.0x ("sped up") | Dialect report, WER heatmap, hatched low-n cells |
| 38 to 43.7 | 06_audit 10-18 s (3x), 18-45.3 s (9x, the transcription and scoring wait, "sped up") | Audits upload form, submit, wait |
| 43.7 to 49.4 | 06_audit 45.3-51 s, 1.0x | Audit verdict, flags |
| 49.4 to 55 | 07_hubspot 3-17 s, 2.5x ("sped up") | Integrations, HubSpot (demo), Deliveries tab |
| 55 to 63 | 08_github 3.5-9.5 s and 11.5-17.5 s, 1.5x | red run, green run |
Dropped from the raw clips: page loads, idle waits, the first and last seconds of each clip. Nothing was re-ordered, no frames were synthesized.

## Deviations from docs/demo-script.md (honest list)
- **No terminal shot** (CLI run): the first 6 s of the script. Not recorded; the demo starts at the web app.
- The failing cell is **amber (71.25), not red**, and **not critical**: the planted `no_amount_confirm` bug produced a clear judge failure with cited turn 6, but the judge did not report the "four thousand vs forty thousand" story. The captions say only what the judge said. The "red cell" click is on the failing cell of a 1x1 matrix (1 call). The pass rate shown is the real one (0% of 1; the PRD 72% is not quoted).
- The Compare page shows a banner that the two runs used different agents (bug agent vs clean agent); it was left in the clip.
- **HubSpot app not shown**: no HubSpot web session exists in the sandbox. The shot shows the integration's Deliveries tab (succeeded, HTTP 201, external id = the note id), and `note_fetched.json` is the HubSpot API record of the note. The Audits UI upload carries no phone, so the HubSpot note comes from a second audit of the same recording through the signed webhook (recording served from the raw GitHub URL of `demo_call.wav`), not from the call shown in the audit shot.
- Dialect: subset only (see above), so no dialect finding is claimed; the caption says n = 4.
- Playwright (Python 1.63.0) and `certutil` import of the proxy CA were used for the GitHub pages; TLS verification was not disabled.
- Observed product issue (not fixed here): the call page stops polling when an uploaded call reaches an evaluating state, so it needs a reload to show the verdict (the recording script reloads).

## HubSpot cleanup
Test note 415570741977 and test contact 584973108949 deleted through the HubSpot API after recording (DELETE 204 each; GET afterwards returns 404 for both). The two integrations in the local stack still exist (ephemeral container).

## Reproduce
`docker compose ... up` stack as in proof/EVAL-06/proof.md, then `python3 scripts/demo/prerun.py no_amount_confirm`, `python3 scripts/demo/dialect_load.py 4`, `python3 scripts/live_make_recording.py ~/demo/call.wav stereo` (in the api container), `python3 scripts/demo/hubspot_live.py`, `python3 scripts/demo/record_demo.py`, `python3 scripts/demo/edit_demo.py`.
