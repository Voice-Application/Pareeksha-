# VOICE-02 verified
Date: 2026-10-23 | SHA verified: b64218f (task/VOICE-02) | Verifier: independent, fresh venv (py3.13)

Re-run: pytest (72 passed, 0 failed, 0 skipped/xfail; coverage pareeksha.audio 97%), ruff check + format --check clean,
render_proof.py (snr_table.txt identical to builder's; all 9 WAVs byte-identical to builder's; copy in verifier/snr_table.txt).
Own check: same seed -> identical bytes on all 8 profiles; different seed differs on all 6 noisy profiles; 8 distinct outputs.
Scan: no STUB/TODO/FIXME/NotImplementedError/skip/xfail/noqa/type-ignore/secrets in changed files.

Done-when (AGENTS §7 / SCOPE): 8 profiles distinct, SNR +/-0.5 dB (measured 0.000 dB error), determinism, chunked==whole: met.

Spec deviations judged non-blocking (neither is in the VOICE-02 done-when):
- Noise is procedural (noise.py), not data/noise/<category>/*.wav + LICENSES.md (TRD §6, 07-file-structure). Licence/clip
  sourcing is tracked under PJM-01; procedural noise is licence-free. Follow-up: swap in real clips later if wanted.
- Profiles in audio/profiles.py (BUILTIN_PROFILES) not data/seeds/noise_profiles.yaml; the yaml seed is consumed by the API-02
  seed script. API-02 must load/mirror these 8 definitions (values match rubric §7).
