# VOICE-02 proof — Audio DSP + LineSimulator (8 profiles)

Built (backend/pareeksha/audio/): `dsp.py` (SNR mix, speech-active mask, A-law/mu-law via audioop, clipping,
stateful band-pass and x2 resampler), `noise.py` (5 procedural, seeded noise categories; no licensed clips),
`profiles.py` (8 rubric §7 profiles), `line_simulator.py` (`LineSimulator`: streaming `process`/`flush`,
`simulate` whole-clip two-pass for exact SNR). Tests: backend/tests/unit/audio/test_line_simulator.py (synthetic fixtures only).

Reproduce (Python 3.13; pip install numpy scipy soundfile audioop-lts pytest):
    cd backend && python3 -m pytest -q            # expect: 72 passed (pytest.log)
    cd backend && PYTHONPATH=. python3 ../proof/VOICE-02/render_proof.py   # snr_table.txt + audio/*.wav
    cd backend && ruff check . && ruff format --check .

Expected: measured SNR equals target (snr_table.txt, within 0.001 dB offline; tests assert +/-0.5 dB offline and
for streaming with reference speech power), chunked == whole bit-identical for chunk sizes 320/100/777/5000 on all 8
profiles, same seed -> identical output, 8 profile WAVs audible and pairwise distinct.
Commit SHA: see git log on branch task/VOICE-02 (final report).
