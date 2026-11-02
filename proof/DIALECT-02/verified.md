# DIALECT-02 verified: PASS

- Date: 2026-10-30
- SHA verified: `6c8e4d6` (branch `task/DIALECT-02`, base `5ccf328`), clean `git worktree`, fresh venv, fresh Compose project `dialectv` (own ports 19094/15432/18000, own volumes, removed with `down -v`).
- Raw outputs: `proof/DIALECT-02/verifier/`.

## Commands re-run
| proof.md step | result | file |
|---|---|---|
| `scripts/data/fetch_vaani.py` into a separate dir (HF_TOKEN, pinned dataset commit `9e6ed4f9`) | **byte-identical**: `manifest.csv`, `sources.json`, `SOURCES.md`, `REVIEW.md`, `fetch_log.txt` and all 110 WAVs (sha256) match the committed data. Selection is deterministic (sorted shard order, round-robin over sorted speakers, no RNG). | (diff run inline) |
| compose up (`api outbox-relay dialect retrier dlq-recorder`, proxy overlay + keys.yml, Docker Hub 429 -> images from mirror.gcr.io) | healthy | `*.log` |
| `proof/DIALECT-02/live_run.py` (real API: CSV + ZIP upload, evaluate, poll) | `upload: accepted 110, rejected []`, `expected_results 330`, 330/330 in 822 s, real Gnani Prisma + real DeepSeek, concurrency 1 (single dialect consumer) | `live_run.txt`, `report.json`, `report.html`, `clips.json`, `usage.json` |
| DB check | 110/110 samples consented, 330 `asr_results`, 330 dialect events processed | `usage.json` |
| backend pytest `tests/unit tests/evaluation tests/judge tests/contract` with `--cov=pareeksha` | 991 passed, 1 failed (`test_schema_dts_fresh`, needs `npm ci` in `web/`, environment only, same as builder); after `npm ci` it passes (1 passed). 0 skipped, 0 xfail. **Coverage 75 %** (TOTAL line; workers 0 % because integration tests need Kafka/Postgres env and are out of this run's scope) | `pytest.txt`, `pytest_dts.txt` |
| `ruff check`, `ruff format --check` (backend, `scripts/data`, `proof/DIALECT-02`) | clean | `lint.txt` |
| `mypy` | see Observations (5 errors, all in files this task did not touch) | `lint.txt` |

## Numbers vs recorded (WER %, my run / builder; n = 22 in all 15 cells)
Max |dWER| 2.3 points (`compare.txt`). Same ordering of groups in every condition:
hi-standard 6.8/6.8 (clean) < kn-en-mix 28.3/28.3 < kn-coastal 33.8/33.8 < kn-mysuru 50.6/50.6 < kn-north 60.9/60.9.
The 10 dB street condition moved most (hi 8.6 vs 10.4, kn-en-mix 32.8 vs 30.6, kn-north 65.5 vs 63.9): STT is non-deterministic on noisy audio and the noise is seeded per run. Clean and A-law cells differ by <= 0.1 point in WER and CER. Intent flag differs by at most 5 points (LLM variance). Every CI brackets its point estimate.

## "Done when" checklist
- [x] >= 3 Kannada groups + Hindi + code-mixed: kn-mysuru, kn-north, kn-coastal, hi-standard, kn-en-mix (22 clips each, 110 total).
- [x] n and speaker-grouped CI in every cell: 15/15 cells have `n=22` and a 95 % `wer_ci` (`compare.txt`); speakers per group 22/22/22/17/22.
- [x] HTML report renders: `GET /dialect-reports/{id}/html` returns 13.7 kB, parses, has a table, all 5 groups and CI text (`verifier/report.html`).
- [x] consent=true on every sample: 110/110 in `manifest.csv` and in the DB (`dataset_checks.txt`, `usage.json`).
- [x] Licence attribution and citation in `data/dialect/vaani/SOURCES.md` (CC-BY-4.0, attribution line, BibTeX `@misc{pulikodan2026...}`).
- [x] No clip in the wrong group. (a) All 110 clips: Vaani district in the group's allowed districts and language matches (`dataset_checks.txt`). (b) 10 clips (2 per group, random seed 7) checked by my own code directly against the Hub parquet at the pinned commit: file name, state, district, language and raw transcript match, 10/10, 0 mismatches (`spotcheck.txt`).
- [x] kn-en-mix is really code-mixed: all 22 clips have >= 2 Latin-script English glosses and >= 10 % of the words (e.g. `ಬೋರ್ಡ್{board} ... ಹೆಲ್ಮೆಟ್{helmet} ಅಂಡ್{and} ... ಸೇಫ್{safe}`).

## Diff scan (`git diff 5ccf328..6c8e4d6`, outside tests/ examples/ data/ proof/)
Changed non-test files: `CHANGELOG.md`, `NOTES.md`, `scripts/data/fetch_vaani.py`. No `STUB(`, TODO, FIXME, NotImplementedError, skip/xfail, `noqa`, `type: ignore`, or secrets; the report numbers come from the API/DB, not from code (`diff_scan.txt` is empty). No backend code changed.

## Observations (not failures)
1. **mypy is not fully clean: 5 errors** in `mock_agent/policy.py` and `backend/tests/unit/speech/test_deepgram.py`, neither touched by this task. `backend/requirements-dev.txt` has `mypy>=1.10` (unpinned), so a newer mypy/typeshed reports them. Not caused by DIALECT-02, but someone should pin mypy or fix those lines. The builder disclosed this.
2. Kannada references are verbatim colloquial Vaani spellings, so Kannada WER (34-65 %) is inflated by spelling convention; CER and intent are the fairer numbers. The builder says this in proof.md; I agree with it. The 5 groups are therefore comparable with each other but not with a standard-orthography WER.
3. 68 of the 88 non-kn-en-mix clips also contain a Latin gloss (Kannada speakers use loanwords everywhere), so the kn-en-mix group is "more code-mixed", not a pure contrast with the other groups.
4. Dialect labels are the speaker's district of residence, not a listened accent judgement (stated in SOURCES.md). Nobody listened to the clips; `REVIEW.md` is for the owner.
5. `live_run.py` writes its outputs next to itself, so running it in a checkout overwrites the committed proof files; I saved mine under `verifier/` and restored the originals.
6. Gnani: 12 log lines with 429 (builder 88) and 9 clips hit HTTP 504 and were redelivered by the retrier; all 330 finished, DLQ empty. Only start-up aiokafka coordinator warnings otherwise.
7. Spend by this verification (one run): Gnani 2,840.9 s of audio (330 calls), DeepSeek 137.6 k tokens (298 calls). No price configured; same upper bound as the builder (< $3), under the $8 budget.
