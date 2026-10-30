# VOICE-07 live round trips (task/LIVE-ACCEPT)
`python scripts/smoke_speech_live.py proof/VOICE-07/live` (through `pareeksha.speech`, one TTS then one STT per vendor, English, one call each):
- ElevenLabs: TTS ok, Scribe v1 transcript equals the text (11/11 words). `elevenlabs_roundtrip.json/.wav`.
- Deepgram: Aura-2 TTS ok, Nova-3 transcript equals the text (11/11 words; punctuation differs). `deepgram_roundtrip.json/.wav`.
- Bug found and fixed by this run: Deepgram TTS returns a streamed WAV whose header has a placeholder data size, so `duration_s` came out as 67106 s; `speech/wav.py::wav_info` now caps the frame count by the bytes present (unit test added). Re-run output: `roundtrip_output.json` (3.6 s).
- Google, Azure, Gemini: unit tests only (no keys).
