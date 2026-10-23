# VOICE-01 verified (independent QA)
Date 2026-10-23 · SHA cc4cea0b6b39ab3bd1da6c7eb80382fd0e5b2c73 · fresh worktree + fresh venv (py3.13)
- pytest (backend, `--cov=pareeksha.gnani`): 193 passed, 0 failed, 0 skipped/xfail; coverage 99% (clients.py line 94 missed).
- ruff check + format --check on pareeksha/gnani, tests/unit/gnani, scripts: clean.
- Scan of diff (non-test code): no STUB/TODO/FIXME/NotImplementedError/skip/xfail/noqa/secrets.
- Real Gnani run of scripts/smoke_gnani.py (1 run): kn Lakshmi/Avinash and hi Shivani/Shubham TTS->REST STT round-trip (WER 0.33/0.33/0.40/0.40, only acronym spacing differs; same as builder); stream STT hi: 1 segment, same text; batch STT kn diarization: 2 segments, speakers [1,2].
- Saved WAVs valid (RIFF/WAVE, 16 kHz mono, 4.56-9.84 s, normal headers); transcripts plausible. Outputs in proof/VOICE-01/verifier/. Credits: verifier/credit_use.md (11 calls, 23.36 s TTS, 33.6 s STT).
- NOTES.md has findings, COST_* (calls/seconds; SDK exposes no balance) and chosen voices.
Caveat: "voices auditioned" was done via STT intelligibility only; no human listened (builder disclosed). Accepted as a proxy; owner may want an ear check.
