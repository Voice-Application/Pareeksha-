# EVAL-07 rejected (verifier, 2026-11-02, SHA aa07ff1)

**One blocker: `mypy` is not clean** (`cd backend && mypy`, pinned mypy 2.4.1, GOAL item 6 / "lint clean").
13 errors in 4 files, all in code this branch added (full output: `verifier/mypy.txt`):
- `mock_agent/vad.py:62` (2): `Generator has incompatible item type "int"; expected "bool"`; `rms` given a `bytearray`.
- `mock_agent/llm_dialog.py:164`: `json=` argument is `dict[str, object]`, not `JsonType`.
- `tests/unit/mock_agent/test_llm_dialog.py` (4): bare `dict`, and `RuntimeError` passed to `dialog()`.
- `tests/unit/test_calibration_import_labels.py` (6, EVAL-06 code): bare `dict`, `round(float|None)`, untyped `cal`.
ruff check and ruff format are clean. The proof claims "mypy clean"; that does not hold.

Everything else passed (details in the list below; nothing else needs rework):
1. EVAL-06 kappa recomputed with `compute_calibration` from labels.csv + .key.json + judge_results.json:
   **0.1892, n=30** (owner passes 5, judge 11). DB dump has 30 `human_reviews` (preetham; 10 + 20; posted via the
   API, `dimensions={}`). Importer stops if `/calibration` n != expected / != labelled rows (import_labels.py:776,782).
2. v2 in-sample: independent recompute **0.6087** (n=30, judge pass 4, owner 5); labelled IN-SAMPLE in the proof.
   rubric-2026-10-v2 active in a fresh DB (seed run), v1 yaml and `judge_v1.j2` untouched, gate (any dim <=1,
   intent_miss, loop) and the two critical rules match `recalibration_plan.md`. No openapi/schema change;
   `test_schema_dts_fresh` passes after `npm ci`.
3. Live clean calls (own stack, `verifier/live*.json`): "already paid" (Priya, clean_16k) judge pass 97.5, agent asked
   for the UTR and noted it; "when is it due" (Deepa, Kannada) pass 100, agent gave 4,500 and the 5th both times it was
   asked. No invented numbers. Babble call (Sunita, pstn_office_babble_15db, Hindi): agent spoke, answered
   "already paid" with UTR request, pass 97.5.
   `make verify-step N=4`: **PASS, 4/5 caught**, control 2/2 (ignore_interrupt 0/2 on this run; was 1/2 in the proof).
4. VAD: unit tests pass; live babble call above is on the final VAD. The held-out batch and V4 ran on the first VAD
   (no speech in the first 0.5 s). That affects how the mock agent behaved in the 30 held-out calls (callers who speak
   at once), not how the judge scores a recorded call, so it does not invalidate the held-out kappa test; mention it
   when the owner labels.
5. Packet `labelling/EVAL-07`: no bug name, scenario, persona, noise name, gate string or judge output on any H*.html or
   index. `.key.json` maps H-id -> call_id only. GUIDE.md states the pass rule generically (80+, gate), not per call.
6. pytest (unit, evaluation, judge, contract): 1083 passed, 0 failed, 0 skipped, once the package is `pip install -e`'d
   and `npm ci` is done (without them 4 env-only failures: 3 entry-point, 1 dts; same on main).
7. Diff scan outside tests: no STUB/TODO/FIXME/NotImplementedError, no skips/xfail, no blanket ignores
   (only `# noqa: E402` on script imports), no hardcoded results.
Held-out kappa: awaiting owner labels (not a failure).
