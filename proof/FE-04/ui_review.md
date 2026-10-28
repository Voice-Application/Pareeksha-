# FE-04 UI self-review (light + dark Playwright screenshots vs docs/design/mock-call-detail.html and direction.md)

Reviewed `screenshots/call-critical-kn-*`, `call-audit-upload-*`, `call-pass-*` (real Kannada and Hindi calls, real audio) against `proof/DES-01/call-detail-*-1440.png`. Fixes applied, then re-shot.

1. Failure tags pointed at the wrong turns: `wrong_fact` showed on turn #0 because a check's evidence (the correct amount stated at #0) was preferred over the judge's evidence for the dimension. The judge's dimension evidence is now the anchor, the check's turns the fallback.
2. Header actions dropped under the description when the title wrapped (mock keeps them top right). `PageHeader` no longer wraps its action group at 860px and up (affects every page, all improved).
3. Uploaded recordings drew two empty speaker lanes and a Latency lane of `0.0 s` bars (the platform has no latency for recordings). Uploads now draw one MIXED lane with diarisation regions (agent/caller tint) and no latency lane; latency tiles say "not measured on recordings"; per-turn "0.0 s to respond" chips are not drawn.
4. Uploads had no way to see or swap the speaker mapping (spec: Speakers panel). Added `Speakers` panel with "Speaker 1 = Agent" and a confirm dialog for Swap (the endpoint is an API-05 stub, so the dialog reports it as unavailable).
5. The "2.0 s target" label collided with latency bar values; it now sits in the left gutter at the dashed line.
6. The "Filter turns" and "Sort" segmented controls showed their label text above the control; they are now screen-reader-only labels (`hideLabel`).
7. The sidebar did not highlight Runs on `/calls/[id]` and the top bar was blank; a call is reached from a run, so Runs stays lit and is the breadcrumb.
8. Verified, no change needed: Kannada/Devanagari carry `lang`, line-height 1.75 and Noto fallbacks render; evidence turns have the 3px fail edge plus tint; selected turn has the accent outline; critical dimension badge and Critical verdict are the only solid fills; score numbers always printed; no gradient, glow or shadow on panels.
