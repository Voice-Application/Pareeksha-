# VOICE-07 live verification, independent QA 2026-10-30
`scripts/smoke_speech_live.py` run by the verifier inside a fresh API container with the verifier's keys (one TTS + one STT per vendor, through `pareeksha.speech`). Outputs in `proof/VOICE-07/verifier/`.
- ElevenLabs: TTS 3.20 s, Scribe transcript equals the reference, 11/11 words. **PASS**
- Deepgram: Aura-2 TTS 3.28 s (duration correct, the WAV header fix holds), Nova-3 transcript 11/11 words (punctuation differs). **PASS**
Google / Azure not live-tested (no keys).
