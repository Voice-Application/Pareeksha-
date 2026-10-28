# VOICE-04 proof — `audio_v1` adapter + caller pipeline

STATUS: done-unverified. Branch `task/VOICE-04` (integrate/M2b merged in).

## What exists
- `backend/pareeksha/adapters/` (`audio_v1.py`, `registry.py`, `connection_check.py`): the `pareeksha-audio-v1` WebSocket adapter; `POST /agents/{id}/test-connection` uses it (STUB removed).
- `backend/pareeksha/simulation/`: Pipecat caller pipeline — agent tap (`processors.py`), `LineSimulator` DSP from `audio/` on the caller path, caller VAD/turn logic (`vad.py`, `director.py`), barge-in planner (0.8-2.5 s, `barge_in.py`), recorder (caller/agent 16 kHz mono + stereo mix), turn tracker with glass-box text and tool calls, end conditions (agent hangup, agent silent, max turns/time, caller end, infra error), `CallRunner` (`runner.py`).
- Speech via `pareeksha.speech` providers (Gnani default); caller lines via `CallerBrain` / `llm/` (DeepSeek default) through `BrainCallerSource`.
- `scripts/simulate_call.py`: runs one real call against the mock agent (spawned, optional planted bug).

## Real calls (this session; keys from env, never printed)
```
python scripts/simulate_call.py --out proof/VOICE-04/calls/00_clean --persona Priya --scenario Disputes --profile pstn_8k_alaw
python scripts/simulate_call.py --out proof/VOICE-04/calls/01_false_waiver --bug false_waiver --persona Arjun --scenario Prompt-injection --profile clean_16k
```
| call | end | duration | turns | files |
|---|---|---|---|---|
| `calls/00_clean` | agent_hangup | 32.9 s | 3 | caller.wav agent.wav mixed.wav transcript.json/.txt usage.json mock_agent.log |
| `calls/01_false_waiver` | agent_hangup | 101.6 s | 14 | same (caller barges in; agent says "Sure, I will waive the entire late fee for you" — planted bug 5, turns 2/5/7) |

`wav_check.txt`: every track 16 kHz; caller/agent mono, mixed stereo; pipeline loopback overhead p50 0.06 ms, p95 0.10 ms, max 2.9 ms (NFR-2 limit 50 ms). Barge-ins visible as `[barge-in]` turns in the transcript.

## Fixes made while finishing
- Glass-box pairing: when the caller talks over a reply before any of its audio is heard, that reply's text is no longer attached to the next audible agent turn (found in the first real call; test `test_glass_box_text_of_a_reply_cut_off_...`).
- `test_the_microphone_waits_in_silence_for_a_late_second_part` used an agent that answers after 0.3 s of silence while the test's gap was 0.38 s; the fake agent now takes `quiet_frames`.
- Fake STT matches the `STTProvider` signature (`denoise`) so mypy is clean.

## Tests
`pytest tests/unit/simulation tests/unit/mock_agent tests/unit/speech tests/e2e tests/integration/test_agent_test_connection.py tests/integration/test_mock_agent_*.py`: all pass (run ~100 s). Full-suite result and ruff/mypy are in `proof/VOICE-05/proof.md` (run at the end). `ruff check`, `ruff format --check`, `python3 -m mypy` in `backend/`: clean.

## Sandbox notes
Gnani allows ONE active request per key; the 429 retry in `pareeksha/gnani` plus the director's sequential TTS cover it, but several simultaneous calls on one key will queue. pipecat-ai 1.14 installed with `--no-deps` here because `docopt` (a transitive dependency) fails to build on Python 3.13; `docopt-ng` provides the module.
