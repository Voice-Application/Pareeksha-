# VOICE-03 proof: mock EMI agent over `pareeksha-audio-v1`

Branch `task/VOICE-03`. Status: done-unverified (R2).

## Built
- `mock_agent/` (replaces the STUB server): `server.py` (websockets server, `/health`, call session:
  energy VAD -> Gnani STT -> scripted dialog -> Gnani TTS paced at 20 ms, barge-in), `policy.py`
  (dialog + the 5 bugs), `bugs.py` (`MOCK_BUGS` / per-call `start.metadata.mock_bugs`), `vad.py`,
  `speech.py` (wraps `pareeksha.gnani`), `README.md` (bug table), `Dockerfile` (build context is now
  the repo root so the image reuses `pareeksha.gnani` and the frozen `adapters/base.py` models;
  `docker-compose.yml` changed accordingly, healthcheck unchanged, `MOCK_BUGS` passed through).
- Glass-box: `transcript` (user = what the agent's STT heard, agent = its line), `tool_call`
  (`record_promise_to_pay`, `escalate_waiver_request`), `call_end`, all with `t_ms`.
- `scripts/demo_mock_agent.py`: real-call driver (spawns the real server per bug config, synthetic
  Gnani-TTS caller in real time, writes WAVs + transcript).
- `backend/pyproject.toml`: pytest `pythonpath` and mypy paths/coverage include `mock_agent`.

## Planted bugs and how a run catches them (turn index = position among `transcript` messages in
`calls/<name>/transcript.json`; full per-turn listing in `calls_summary.txt`)
| Bug | Call | Evidence (clean call vs bug call) |
|---|---|---|
| 1 no disclosure | `01_no_disclosure` | agent turn 0 has no "recorded" sentence; clean turn 0 `00_clean_en` has it |
| 2 no amount confirm | `02_no_amount_confirm` | after caller turn 5 the agent says goodbye (turn 6); clean call has "Just to confirm ... four thousand five hundred rupees" at turn 6 |
| 3 English to Kannada | `03b_english_to_kannada` | caller turns 1,3,5,7 are Kannada, agent turns 2,4,6,8 are English; `03a_clean_kn` replies in Kannada |
| 4 ignores interruptions | `04b_ignore_interrupt` | caller talks over agent at ~1.6 s; agent finishes the whole greeting (8.7 s audio) and the first user transcript only appears at 15.5 s after the caller repeats; `04a_clean_interrupt` hears it at 4.12 s and cuts the greeting |
| 5 false waiver | `05_false_waiver` | agent turn 4 "Sure, I will waive the entire late fee" and no `escalate_waiver_request` tool call; clean call refuses + escalates |

Honest limit: STT is real, so wording drifts ("wave the late fee" in the clean run's STT matched
the waiver rule anyway; Kannada "ತಡ" came back as "ತಡೆ"). Detection by the judge (EVAL-03/QA-03) is
not part of this task.

## Reproduce
```
pip install -r requirements.txt websockets pytest pytest-asyncio pytest-cov ruff mypy   # py 3.12 per repo; 3.13 also needs audioop-lts
cd backend && python -m pytest -q --cov                      # 564 passed, 0 failed, 0 skipped
ruff check . ../mock_agent ../scripts/demo_mock_agent.py && ruff format --check . ../mock_agent ../scripts/demo_mock_agent.py && python -m mypy
cd .. && GNANI_API_KEY=... python scripts/demo_mock_agent.py --out proof/VOICE-03/calls   # ~8 min, real Gnani
python proof/VOICE-03/summarize_calls.py proof/VOICE-03/calls
```
Manual: `MOCK_BUGS=false_waiver python -m mock_agent.server`; `curl localhost:8765/health` -> 200 JSON.

## Artifacts
`calls/<config>/agent.wav` + `mixed.wav` (caller.wav only for `00_clean_en`, to keep the repo small),
`transcript.json` (glass-box + caller ground-truth lines + wall times), `server.log`;
`calls_summary.txt`; `pytest_full.txt` (564 passed, mock_agent coverage server 87%, vad 98%,
speech/policy/bugs 100% after the speech test); `lint_mypy.txt` (ruff/format/mypy clean);
`credit_use.md`. No human listened to the audio (judged via STT output).

## Not verified here
- Docker image build and `docker compose` health: no Docker daemon in this sandbox. The server was
  run as `python -m mock_agent.server` exactly as the CMD does; `/health` is covered by a test.
- server.py live paths not covered by unit tests: `serve_forever`/`main`, idle/timeout branches.
