# VOICE-06 proof — Pipecat adapter, `PareekshaFrameSerializer`, `examples/pipecat-bot`

STATUS: done-unverified (Must part). LiveKit (Should) and Vapi (Could) are NOT built; `get_adapter("livekit")` still raises `AdapterUnavailableError`. Cutting them needs the owner's written approval (AGENTS §10); not claimed here.
Branch `task/VOICE-06` (from `task/VOICE-04` e5e3b9b).

## What exists
- `backend/pareeksha/adapters/pipecat_serializer.py`: `PareekshaFrameSerializer` (Pipecat `FrameSerializer`: binary <-> 16 kHz `InputAudioRawFrame`/resampled `OutputAudioRawFrame`, `start` remembered (`.start_message`, `.language`), `stop` -> `EndFrame`, End/Cancel -> `call_end`, glass-box transport messages pass through) and `GlassBoxProcessor` (user/agent transcripts, tool calls from `TranscriptionFrame` / LLM text / `FunctionCallResultFrame`, sent as urgent transport messages).
- `backend/pareeksha/adapters/pipecat_adapter.py` + registry: `PipecatAdapter` (`agents.adapter = "pipecat"`); same wire as `audio_v1`, plus re-framing of agent audio into 20 ms frames. `audio_v1.py` got two small hooks (`_on_binary`, `session_class`); behaviour unchanged.
- `examples/pipecat-bot/` (`bot.py`, `speech_services.py`, `requirements.txt`, `README.md`): Gnani STT -> DeepSeek -> Gnani TTS, Silero VAD, `record_promise_to_pay` tool, `/health` + `/ws`.
- `backend/tests/contract/test_adapter_contract.py` (FR-DX-7): the same assertions run against the `audio_v1` mock agent and the Pipecat example bot through the production adapters; `tests/unit/test_pipecat_serializer.py`.
- `scripts/simulate_call.py --adapter pipecat`.

## Real call (real Gnani STT/TTS, DeepSeek caller and bot; keys from env, never printed)
```
PYTHONPATH=backend:examples/pipecat-bot:. python examples/pipecat-bot/bot.py &        # :8766
PYTHONPATH=backend:. python scripts/simulate_call.py --out proof/VOICE-06/calls/00_pipecat_clean \
  --adapter pipecat --agent-url ws://127.0.0.1:8766/ws --persona Priya --scenario Disputes \
  --profile clean_16k --max-seconds 100
```
Result (`calls/00_pipecat_clean/`): 100.0 s call (ended by the 100 s cap), 8 turns, caller/agent 16 kHz mono + stereo mix WAVs, `transcript.txt/.json` with the bot's own glass-box text on every agent turn, pipeline overhead p95 0.14 ms. The bot opens with the disclosure ("automated assistant ... call may be recorded"), the caller disputes the amount, the bot declines to break down charges. Glass-box agent text now arrives with the audio (first attempt sent it after the audio played; fixed by using urgent transport messages).
Latency finding: caller-end to bot-audio-start is ~6 s (segmented REST STT + LLM + whole-sentence TTS); fine for testing, not a production-latency example.
Spend: `credit_use.md`.

## Tests
`proof/VOICE-06/pytest_full.txt` (full backend suite against a private Postgres 16 and Kafka: `TEST_DATABASE_URL`/`INFRA_TEST_*` pointing at localhost:55432 / :59094). `ruff check`, `ruff format --check`, `python3 -m mypy` in `backend/`: clean (see `lint_types.txt`).

## Not covered / notes
- `pipecat-gnani` 0.5.12 does not import with `gnani-vachana` 0.8.2 (`TIMBRE_V20_VOICES` missing); the example wraps `pareeksha.speech` providers instead (NOTES.md).
- Silero VAD does not fire on synthetic tones; the contract test injects an energy VAD via `create_app(..., vad_factory)`. The real call used Silero.
- LiveKit adapter + example not built.
