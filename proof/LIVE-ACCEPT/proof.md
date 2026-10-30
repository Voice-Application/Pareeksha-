# LIVE-ACCEPT proof (branch task/LIVE-ACCEPT, from origin/main 2d1a62f)

Live HubSpot acceptance (GOAL items 5 and 6, V5, V10 guide 5) with the owner's HubSpot private-app token. Synthetic data only: contact "Pareeksha SyntheticTest", fake phone +919999900042 (guide run: "Pareeksha GuideTest", +919999900043); the recording is two TTS voices (Gnani Timbre, hi-IN, 13.6 s, `two_speaker_call.wav`, made by `scripts/live_make_recording.py`).

## Result
- HubSpot auth: 200. Integration test: `{"ok":true,"detail":"HubSpot token accepted"}`.
- Signed webhook POST at 16:18:10.7 UTC -> note **412826916601** created in HubSpot at 16:18:19.8 UTC (`hs_createdate`) = **9.1 s** after the POST; V5's poll saw its delivery row after 15.1 s (`V5.md`, STATUS PASS, limit 180 s).
- Proof the note is on the contact: `note_fetched.json` (HubSpot API GET /crm/v3/objects/notes/412826916601 with associations: contact 579634530018, type note_to_contact, body = the audit summary + link); `contact.json`.
- Duplicate delivery + crash (`dup_crash.log`, script `scripts/live_dup_crash.sh`): the original `evaluation.completed` re-published twice, integrations worker SIGKILLed and restarted: notes on the contact before 1 [412826916601], after **1** [412826916601]; evaluations for the call 1; no new delivery rows. (Two HubSpot integrations existed from an aborted first V5 attempt: the second recorded "note ... already on contact", i.e. the idempotency marker works across integrations too; `deliveries_*.json`.)
- Guide 5 from a fresh clone (`proof/DOC-02/guides/5.log`): note 412779237078 on contact 579787952831, 11 s after the POST, exactly one note; RESULT: PASS. `scripts/verify run_all.sh 10` (V10): PASS.

## Findings
1. **Gnani batch STT (diarized) failed server-side** during this session: every batch job ended FAILED with no reason, including the VOICE-01 recording that passed earlier (job ids 28a15726..., 89decaa7..., 70307450...); REST STT works. The audit therefore used `STT_PROVIDER=elevenlabs` (Scribe, diarizes the two speakers correctly: 3 segments, speaker_0/speaker_1). Re-test Gnani batch before relying on it.
2. Guide 4 section 4 (local recording) was wrong on Linux and broke the speech provider: fixed (system CAs kept in `SSL_CERT_FILE`, `extra_hosts: host.docker.internal:host-gateway`).
3. V5 now accepts `HUBSPOT_ACCESS_TOKEN` and `VERIFY_RECORDING_LANGUAGE`.
4. Not exercised live: HubSpot screenshot of the activity feed (the API JSON is the proof); build from scratch (Docker Hub returned 429, images from the same Dockerfiles were retagged); recording hosted by a private https server with `PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1` (the SSRF guard otherwise refuses private hosts).

## Reproduce
`scripts/live_make_recording.py`, serve the WAV over https, then `VERIFY_RECORDING_URL=... VERIFY_CONTACT_PHONE=... VERIFY_RECORDING_LANGUAGE=hi-IN make verify-step N=5`; `scripts/live_dup_crash.sh <call_id> <contact_id>`.
