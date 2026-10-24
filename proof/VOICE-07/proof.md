# VOICE-07 proof: pluggable speech providers

Branch `task/VOICE-07` (from `claude/amazing-einstein-agkccc` 51b62cd). Commit SHA: see `git log -1 task/VOICE-07` (the commit contains this file).

## Built
- `backend/pareeksha/speech/base.py`: `STTProvider` (batch `transcribe`, live `transcribe_stream`, `STTCapabilities`: streaming, word timings, word confidence, diarization flag, batch limit) and `TTSProvider` (`synthesize` to WAV at a stated sample rate, `list_voices`, `TTSCapabilities`), value types (`Transcript`, `WordTiming`, `SynthesisResult`, `SpeechUsage`...), typed errors, `SpeechSelection` (per agent/run override).
- `speech/config.py` (`SpeechSettings`, env `STT_PROVIDER`/`TTS_PROVIDER`, default gnani; per-vendor keys, models, voices, `COST_*`), `speech/registry.py` (factory + `provider_status`), `speech/http.py` (retry 5xx/429/timeouts x3, 4xx permanent).
- Adapters in `speech/providers/`: `gnani` (wraps `pareeksha.gnani`, which is unchanged), `google` (STT v2 + TTS v1 REST, service-account via google-auth), `azure` (fast transcription + SSML TTS REST), `elevenlabs` (Scribe + TTS REST), `deepgram` (Nova REST + WebSocket, Aura TTS REST + models list).
- Contract: no existing health/doctor path could carry this (`/health` is the frozen `{db,kafka}`), so `GET /api/v1/speech/providers` was added (scope `read`, never returns keys). Recorded in `docs/contracts.md` section 4, `docs/06-api-spec.md` section 12, `CHANGELOG.md` ("Contract change: speech provider abstraction (owner-approved 2026-10-24)"); contract tests updated (route list, implemented set). `.env.example` has all new variables. `requirements.txt` adds `google-auth`. Vendor API notes + links are in `NOTES.md`.

## Capability matrix (as coded)
| Provider | STT batch | STT streaming | word timings / confidence | diarization | TTS | voice list |
|---|---|---|---|---|---|---|
| gnani | REST + batch job | yes (WebSocket) | no / no | yes (batch job) | yes | static (13 Timbre v3.0) |
| google | yes (sync, 60 s) | no (gRPC only, not wired) | yes / yes | flag on, model dependent | yes | yes |
| azure | yes (fast transcription) | no (needs Speech SDK, not wired) | yes / phrase-level | yes | yes | yes |
| elevenlabs | yes (Scribe) | no (realtime not wired) | yes / yes (logprob) | yes | yes | yes |
| deepgram | yes (Nova) | yes (WebSocket) | yes / yes | yes | yes (English Aura voices) | yes |

## Acceptance status per vendor
- **Gnani: real round trip done.** TTS (Shivani, hi-IN, 29 chars) then STT REST through the abstraction; transcript equals the reference. Output `gnani_adapter_roundtrip.json` / `.wav`; spend in `credit_use.md` (2 calls, 2.56 s + 2.56 s). Streaming and diarized batch of the adapter are covered by unit tests with fakes only (VOICE-01 already proved those SDK paths for real).
- **Google: real-key acceptance pending owner keys.** Unit tests only, HTTP mocked.
- **Azure: real-key acceptance pending owner keys.** Unit tests only, HTTP mocked.
- **ElevenLabs: real-key acceptance pending owner keys.** Unit tests only, HTTP mocked.
- **Deepgram: real-key acceptance pending owner keys.** Unit tests only, HTTP mocked (WebSocket tested against an in-process local server, not Deepgram).
Mocked responses follow the vendors' documented shapes; they do not prove the live APIs behave identically (language-code handling for Deepgram, Chirp diarization, ElevenLabs Indian-language support are the known open points).

## Reproduce
```
cd backend
python3 -m pytest tests -q --cov --cov-report=term     # 593 passed, 0 failed, 0 skipped, total coverage 98% (speech modules 93-99%)
ruff check . && ruff format --check . && python3 -m mypy   # all clean (strict)
cd .. && GNANI_API_KEY=... python3 scripts/smoke_speech_gnani.py proof/VOICE-07
```
Logs: `pytest_full.txt`, `lint_types.txt`.

## Not done / issues
- Streaming STT for google, azure, elevenlabs (flags are `streaming=False`; calling raises `UnsupportedCapabilityError`).
- `api_usage.provider` (docs/schema.sql CHECK and `UsageRow` literal) still lists only gnani/gemini/deepseek/other; persisting usage rows for the new vendors needs an owner-approved schema change. `SpeechUsage` carries provider + `est_cost` ready for it.
- Per-agent/run override exists as `SpeechSelection`, but wiring it into agent/run schemas (frozen) is left to the owning tasks.
