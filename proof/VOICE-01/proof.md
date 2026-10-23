# VOICE-01 proof

Built: `backend/pareeksha/gnani/` (usage ledger, 5xx/timeout retry x3, TTS disk cache, WAV header fix, TTS / REST STT /
WS stream STT / batch STT with diarization wrappers), `scripts/smoke_gnani.py`, 13 unit tests, NOTES.md findings.
Run against real Gnani with synthetic TTS speech only.

## Reproduce
```
pip install gnani-vachana pytest pytest-asyncio pytest-cov ruff numpy scipy soundfile audioop-lts jiwer rapidfuzz requests websockets
export GNANI_API_KEY=...        # or .env
python scripts/smoke_gnani.py --out proof/VOICE-01        # ~17 Gnani calls, ~1.5 min
cd backend && python -m pytest -q --cov=pareeksha.gnani --cov-report=term-missing   # 193 passed, 0 skipped
cd backend && ruff check pareeksha/gnani tests/unit/gnani ../scripts                 # All checks passed
```

## Real results (`smoke_report.json`)
| Check | Result |
|---|---|
| kn TTS->REST STT, Lakshmi + Avinash | round-trips; WER 0.33 each (acronym "ಇ ಎಮ್ ಐ" spelled with spaces) |
| hi TTS->REST STT, Shivani + Shubham | WER 0.30 / 0.40 (acronym spacing, one spelling variant) |
| Stream STT (hi, Shivani clip) | 1 segment, server latency 185 ms, same text as REST |
| Batch STT + diarization (synthetic kn two-voice call, 10 s) | 2 segments, speakers 1 and 2 |

Files: `kn-IN_*.wav`, `hi-IN_*.wav`, `*.transcript.txt`, `stream_hi-IN.transcript.txt`, `batch_kn-IN_call.wav`,
`batch_kn-IN.transcript.json`, `credit_use.md` (17 calls, 23.28 s TTS, 67.04 s STT), `pytest_*.txt`, `ruff.txt`.

## Not done / caveats
- Voices were not auditioned by ear (no human listener in this run); chosen by STT intelligibility only.
- Hinglish/Kanglish code-mixed TTS->STT not exercised (kept credit use minimal).
- Coverage of `pareeksha.gnani`: 99% (one unreachable line). SDK/network calls are faked only in unit tests.
