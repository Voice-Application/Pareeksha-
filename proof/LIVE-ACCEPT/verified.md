# LIVE-ACCEPT verified (independent QA, 2026-10-30)

Verified commit: qa/LIVE-ACCEPT = task/LIVE-ACCEPT 8e6dde9 + merge of origin/main (d9a9974). Fresh clone, private compose project `vlive` (ports 38000/33000/35432/39094), own images/volumes, proxy overlay. Synthetic contacts only (+919999900077, +919999900078); own TTS recording (`verifier/` + Gnani Timbre hi-IN, 13.5 s). Evidence in `proof/LIVE-ACCEPT/verifier/`.

| Item | Result | Evidence |
|---|---|---|
| GOAL 5 / V5 | **PASS** | signed POST 15:23:29 -> note 413923017404 created 15:23:45.085Z (V5 measured 20.1 s, limit 180 s). `note_fetched.json`: fetched back from HubSpot, associated to the contact (note_to_contact), body = audit summary + link. `proof/verify/V5.md`. STT used: **Gnani** (api_usage gnani row), not the ElevenLabs fallback. |
| GOAL 6 live | **PASS** | `dup_crash.log`: original evaluation.completed re-published 2x, integrations worker SIGKILLed 15:24:01 and restarted: notes on contact before 1, after 1 (same id 413923017404); evaluations for call 1. (The one `failed` delivery row is the verifier's own webhook-sink integration to example.com, expected.) |
| GOAL 10 / V10 guide 5 | **PASS** | `guide5.log`, `guide5_note.json`: guide 5 followed step by step (guide 4 sections 1-4 for the recording); POST 15:26:05 -> note 413913993954 at 15:26:21.8Z (16 s); exactly 1 note on the contact. My delivery-poll one-liner had a quoting bug (noted in the log); the note was confirmed directly in HubSpot instead. |
| VOICE-07 live | **PASS** | see proof/VOICE-07/verified-live.md |
| Gnani batch diarization | **WORKS NOW** | `gnani_batch.json`: batch job completed in ~7 s, 3 segments, `speaker` 1 present (one transient 429 on status poll, retried). The builder's "every batch job FAILED" is no longer reproducible; the audit path used Gnani and met its criteria (V5 PASS, speaker roles resolved, evaluation completed). |

## Notes / findings (builder code not changed)
- Docker Hub returned 429 on first pulls here too; retries succeeded. A stale-container name conflict appeared only because two `up` runs overlapped (my doing).
- `make verify` V6 FAILs in this environment: "Kafka suite failed" because the host has no pytest (`No module named pytest`); the functional part of V6 passed (evaluations 1/1, duplicate keys 0, duplicate CRM note ids 0). V6 should not depend on host pytest.
- Not exercised: HubSpot UI screenshot (API JSON used), build from scratch with no cached base images.

## Cleanup
Synthetic contacts 581744433873, 581659657943 and their notes deleted (`cleanup.log`); GETs return 404 and search finds none.
