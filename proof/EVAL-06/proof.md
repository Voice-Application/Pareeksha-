# EVAL-06 (prep half): 30 real calls + blind labelling packet + label importer

GOAL item 9 / V9: judge vs Preetham's labels on 30 calls, Cohen's kappa. Spec: docs/08-evaluation-rubric.md
§2 (rubric-2026-10-v1) and §10 (calibration: human labels blind to the judge), docs/02-requirements.md
FR-EV-8, `GET /api/v1/calibration` (backend/pareeksha/api/routers/system.py), `POST /api/v1/calls/{id}/review`
(backend/pareeksha/api/routers/calls.py → `human_reviews`).

**Status**
- Built and run: real 30-call batch (all 30 evaluated by the judge), blind packet, importer and its unit tests.
- **Owner labels: INTERIM, 10 of 30.** The owner reviewed L01-L10. L11-L30 in the owner's sheet are a
  fill-down; the owner confirmed they were not reviewed, so they are blank in `labels.csv` and awaiting the
  owner. **V9 stays PENDING.**
  - On n = 10, pass/fail: 10/10 agreement (95% Wilson CI [0.72, 1.0]), κ = 1.0 (the API and the offline
    recompute agree). The bootstrap interval for κ is degenerate, because each rater has only 1 pass.
  - Critical: owner 9/10, judge 4/10; agreement 0.5, κ 0.14 (bootstrap 95% CI [0.0, 0.55]).
  - Spearman and per-dimension MAE are **not provided by owner**.
  - L10 is labelled passed=yes **and** critical=yes (fact; for the owner to confirm).
  - Details are in `calibration.md` / `calibration.json`.
- No API or DB contract was changed.

Code commit: `9f2a41f` (full SHA in the Commit section).

## What was built

| file | what |
|---|---|
| `scripts/calibration/run_batch.py` | Runs the 30-call plan, one call per one-cell `POST /runs` at concurrency 1. Clean calls go to the seeded `EMI Reminder Bot`. Each planted bug gets its own mock-agent container (`MOCK_BUGS=<bug>`) and agent `EMI Reminder Bot [bug:<bug>]`, using the same mechanism as V4. It writes `batch.json`; a rerun only redoes cells that have no `ok` evaluation or whose plan changed. |
| `scripts/calibration/export_judge_results.py` | Dumps the stored `evaluations` and `deterministic_checks` rows for the 30 calls from Postgres to `judge_results.json`. This file is evidence and is **not** in the packet. |
| `scripts/calibration/export_packet.py` | Builds the blind packet in `labelling/EVAL-06/` (shuffled L01..L30, mixed audio as MP3, transcript, DeepSeek gloss, index, labels.csv template, `.key.json`). |
| `labelling/EVAL-06/GUIDE.md` | One-page guide: the 7 dimensions with their 0-4 anchors copied from `rubric-2026-10-v1.yaml`, what counts as critical, and "pass = you would ship this call to a real borrower". |
| `scripts/calibration/import_labels.py` | Validates `labels.csv` against `.key.json`, POSTs each row to `/calls/{call_id}/review` (reviewer `preetham`), reads `GET /calibration`, and writes `proof/EVAL-06/calibration.json` + `calibration.md` (kappa, Spearman, MAE per dimension, n, list of disagreements). |
| `backend/tests/unit/test_calibration_import_labels.py` | 15 tests for the validator, the mapping to the review body, CSV/key reading and the disagreement list. |

## Commands (exact)

Stack (sandbox behind a TLS-intercepting proxy; Docker Hub rate-limited the `node`/`python` base image
lookups, so the backend image was built once as `api` and tagged for the other backend services; the web
image was not needed):
```
dockerd &                                   # no daemon was running in the container
cp .env.example .env   # then filled GNANI_API_KEY / DEEPSEEK_API_KEY from env, generated SECRET_KEY + PAREEKSHA_API_KEY, SIMULATOR_REPLICAS=1
export COMPOSE="docker compose -f docker-compose.yml -f docker-compose.proxy.yml" CA_BUNDLE=/root/.ccr/ca-bundle.crt BUILDX_BAKE_ENTITLEMENTS_FS=0
$COMPOSE build api mock-agent
for s in migrate outbox-relay retrier finalizer planner dlq-recorder evaluator reconciler auditor dialect simulator generator integrations; do docker tag pareeksha--api:latest pareeksha--$s:latest; done
$COMPOSE --profile workers up -d --no-build migrate outbox-relay retrier api finalizer mock-agent planner dlq-recorder evaluator reconciler auditor dialect simulator generator integrations
$COMPOSE run --rm --no-deps api python -m pareeksha.seed       # created personas 20, noise_profiles 8, rubric 1, agents 1, scenarios 8
```
Batch, judge export, packet:
```
python3 -u scripts/calibration/run_batch.py >> proof/EVAL-06/batch_run.log   # rerun until "evaluated 30/30"
python3 scripts/calibration/export_judge_results.py                          # -> 30 evaluation rows for 30 calls
SSL_CERT_FILE=/root/.ccr/ca-bundle.crt python scripts/calibration/export_packet.py --seed 406313920
```
Tests:
```
cd backend && python -m pytest tests/unit/test_calibration_import_labels.py -v      # 15 passed
cd backend && python -m pytest tests/unit tests/evaluation tests/judge tests/contract -q
```

## The batch (real Gnani speech + DeepSeek caller and judge, concurrency 1)

Mix: 30 calls in total.
- Languages: 12 Kannada, 9 Hindi, 9 English.
- Noise profiles: `pstn_8k_alaw` ×14, `pstn_office_babble_15db` ×8, `clean_16k` ×8.
- Recorded audio: 43.8 min.

The full plan is in `run_batch.py` and the outcome of every cell is in `batch.json`. Judge results from the DB
(`judge_results.json`):

| agent | calls | judge passed | judge critical | judge overall scores (by cell) |
|---|---|---|---|---|
| clean | 10 | 7 | 1 | 92, 62, 95, 95, 100, 100, 81, 95, 82, 48 |
| no_disclosure | 4 | 0 | 0 | 82, 49, 61, 60 |
| no_amount_confirm | 4 | 1 | 1 | 48, 78, 70, 100 |
| english_to_kannada | 4 | 0 | 0 | 64, 30, 31, 66 |
| ignore_interrupt | 4 | 3 | 0 | 90, 55, 90, 80 |
| false_waiver | 4 | 0 | 4 | 50, 0, 20, 50 |

Across all 30 calls the judge gave 11 pass, 13 fail without a critical failure, and 6 critical. Both classes are
well represented, so kappa will mean something.

**What happened along the way** (full detail in `batch_run.log`; replaced rows are in `batch_replaced.json`
when present):
1. **`pstn_street_10db` was dropped after 3 of 3 calls.** The mock agent stayed mute (`agent_silent`, judge
   score 5, critical). The third call is `44ad7d60-…`: its run was still in flight when the first pass was
   stopped, so it is not in `batch_run.log`, but it is in the DB. Its barge-in VAD treats the steady street noise as speech while the opening is still
   being synthesised, so it cancels the opening before sending any audio. The street cells were changed to
   `clean_16k` and run again. ISSUE-1 below.
2. **The "Caller goes silent" scenario ended `infra_error` 4 times out of 4.** The persona was swapped once,
   then the cell was given another scenario. Reproduced directly in the api container: Gnani TTS
   `synthesize("...", "Riyaa", "hi-IN")` returns `HTTP 500 {"message":"No audio generated during synthesis"}`.
   Normal lines with the same voice synthesise fine. The silent caller's line is punctuation only, so the caller
   TTS retries until it times out. ISSUE-2 below.
3. **One more cell ended `infra_error`** ("caller TTS: TimeoutError") and passed on retry.

All 30 calls in the packet are `evaluation.status = ok`.

**Gnani errors seen.** The Gnani key was shared with other sessions running at the same time (DIALECT-02 and a
verifier). Counts are distinct `request_id`s that failed, from `docker compose logs` at the end of the run; the
speech layer retried each one:

| service | 429 (rate limit) | 500 | 504 |
|---|---|---|---|
| simulator (caller) | 123 | 48 | 4 |
| mock-agent (clean agent) | 25 | 0 | 3 |
| bug mock-agent containers | not counted (logs removed with the containers) | | |

- The 500s are the "No audio generated" failures on the silent caller's `...` line (ISSUE-2).
- 5 calls still failed after retries (`infra_error`); each was re-run and none is counted as a result
  (`batch_replaced.json`).
- No code was changed to hide these errors.

## The blind packet (`labelling/EVAL-06/`, 16 MB)

- `index.html` and `L01.html` .. `L30.html`. Each call page has:
  - an audio player with the caller + agent mix (`audio/L##.mp3`, mono 48 kb/s, metadata stripped);
  - the timestamped transcript (click a timestamp to seek), with the agent's tool calls shown inline;
  - for Kannada/Hindi lines, an English gloss from DeepSeek (`deepseek-flash`), clearly labelled
    "MT gloss … machine translation, can be wrong". Each gloss also gives the model's guess of the language
    actually spoken. This was added after the first export showed that Kannada-language STT writes the agent's
    English speech out in Kannada script (L02), which a plain gloss would hide.
- `labels.csv`: header `label_id,passed,critical,task_completion,policy_compliance,factual_accuracy,language_handling,conversation_flow,empathy_tone,escalation,notes`,
  with L01..L30 pre-filled and everything else empty.
- `.key.json`: shuffle seed 406313920 and L-id → call_id. The packet pages never show call ids.
- `GUIDE.md`.
- **Blindness check**: the call pages were searched for every bug name, `EMI Reminder Bot`, every scenario
  title, persona name, noise-profile name, call id and run id, and for "judge", "passed", "critical",
  "evaluation" and "failure". The only hits were the generic word "score" ("see GUIDE.md for the scores") and,
  on `index.html`, a sentence asking the owner not to look up the judge.
- **What the pages do show**: the scenario's caller goal, synthetic facts and success criteria (the same brief
  the judge gets, identical for clean and bugged agents, needed to score task completion and factual accuracy)
  and the caller's language.
- **Rendering check**: in headless Chromium, the L02 audio loads (91.8 s) and `index.html` has no horizontal
  scroll at 390 px width.

**How the owner opens it locally:**
```
cd labelling/EVAL-06 && python3 -m http.server 8000
# open http://localhost:8000/  (index -> L01..L30), read GUIDE.md, fill labels.csv
```

## Owner labels and calibration (V9)

**Where the labels came from.** The owner's sheet was relayed by the orchestrator session on 2026-10-30
(18:58 UTC), with the owner's mapping decisions:
- `passed`: "passed" means yes; "fail" and "partial" mean no.
- `critical`: kept as written.
- The seven dimension columns (yes/no/ok/o/blank, not 0-4) are treated as not provided.

**`labelling/EVAL-06/labels.owner.csv`** is the owner's raw sheet as relayed. It is kept unchanged.
- L01-L10 are the owner's reviews, copied exactly (stray spaces included).
- **L11-L30 are unreviewed fill-down.** The owner confirmed on 2026-10-30 that they were not reviewed. They
  arrived as one "each row is exactly: …" line and are written out as 20 identical rows. They are not
  labels and must not be imported.

**`labelling/EVAL-06/labels.csv`** is the normalised file:
```
python scripts/calibration/import_labels.py --normalise-owner labelling/EVAL-06/labels.owner.csv \
    labelling/EVAL-06/labels.csv --unreviewed L11-L30
```
- L01-L10 have passed and critical mapped, dimension cells empty and notes kept.
- L11-L30 are blank. The importer treats a blank row as awaiting the owner: it skips the row, marks the
  report INTERIM and keeps V9 pending.

### History: first import on 30 rows, then removal of the 20 fill-down reviews
- **First import.** Before the owner's correction arrived, all 30 rows were imported.
  - `import_labels.log`: 30 posted, κ 0.1124 on n = 30.
  - `import_labels_rerun.log`: an idempotent rerun, 30 × 409.
  - Those numbers are void, because 20 of the rows were never reviewed.
- **Removal.** The API has no endpoint to delete a review, and API contracts are frozen, so the 20 rows for
  L11-L30 were removed directly in Postgres, in one transaction.
  - The SQL is in `remove_unreviewed.sql`. It scopes the delete to `reviewer = 'preetham'` and to the
    evaluations of the 20 L11-L30 calls from `.key.json`. Result: `DELETE 20`, 10 rows left.
  - The 20 deleted rows were saved first, as JSON, to `removed_human_reviews.json`.
  - After the removal, `GET /calibration` returned `n = 10, kappa 1.0`.
- **Guard against stale reviews.** The importer now refuses to write a report when `GET /calibration` counts
  more reviewed evaluations than the file has labelled rows. Stale reviews in the DB would therefore stop the
  import instead of silently skewing κ.

### Current import (INTERIM)
```
python scripts/calibration/import_labels.py --owner-raw labelling/EVAL-06/labels.owner.csv \
    --extra-md proof/EVAL-06/recalibration_plan.md        # log: import_labels_interim.log
```
- **What was posted.** The 10 reviews for L01-L10 were already present: 10 × 409, no new posts.
  - The review API does not require dimension scores (`ReviewCreate.dimensions` defaults to `{}`;
    `overall_score` stays null), so passed and critical went through the real `POST /calls/{id}/review` and
    no scores were invented.
- **Two independent checks, same result.**
  - `GET /calibration` and an offline recompute both give n = 10, κ = 1.0. The offline recompute uses the
    endpoint's own `compute_calibration`, imported, on `judge_results.json`.
  - Before importing, the importer also checks that each call's live evaluation is the one in
    `judge_results.json`.

| pass/fail | owner pass | owner fail |
|---|---|---|
| judge pass | 1 | 0 |
| judge fail | 0 | 9 |

| critical | owner critical | owner not critical |
|---|---|---|
| judge critical | 4 | 0 |
| judge not critical | 5 | 1 |

- **Pass/fail.** Raw agreement 1.0, 95% Wilson CI [0.7225, 1.0]; κ 1.0.
  - The percentile bootstrap (10,000 resamples of calls, seed 20261030) gives a κ interval of [1.0, 1.0],
    but 35.3% of resamples leave κ undefined.
  - With one pass per rater this interval carries no information, and `calibration.md` says so. The Wilson
    interval is the honest uncertainty at n = 10.
- **Critical.** Raw agreement 0.5, Wilson CI [0.2366, 0.7634]; κ 0.1379, bootstrap CI [0.0, 0.5455].
- **Disagreements: 5, all on critical only.** L04, L05, L06 and L07 are critical for the owner but not for the
  judge. L10 is critical for the owner while both rate it a pass.
- **Not a systematic disagreement.** No claim of systematic judge-owner disagreement is made, and no v2
  rubric or prompt is proposed. `recalibration_plan.md` keeps the owner's failure definition (wrong values,
  and non-responsive replies) and the rubric analysis only as **risks to check once 30 labels exist**.
- **V9 is not run:** it stays PENDING until 30 calls are labelled.

### Database dump
- **What it holds.** `proof/EVAL-06/pareeksha_db.sql.gz` (133 KB) is a plain PostgreSQL 16 `pg_dump`,
  re-taken after the removal.
  - It holds the 10 owner reviews (L01-L10) and none for L11-L30; this was checked in the dump text.
  - It keeps every table's rows except `api_keys` (only the table definition), so no key hash is committed.

  | table | rows |
  |---|---|
  | calls | 38 |
  | evaluations (all `ok`) | 33 |
  | turns | 284 |
  | human_reviews | 10 |

- **Test restore.** The dump loads into an empty database with `ON_ERROR_STOP=1` and gives the counts above.
- **What is not in it.** The 38 calls include the replaced and errored ones. Audio is not in the dump; the
  packet's mp3s are its copy.

To restore on a fresh stack (`.env` with `PAREEKSHA_API_KEY` set):
```
docker compose up -d postgres                   # fresh pg-data volume: empty database, before any migrate
zcat proof/EVAL-06/pareeksha_db.sql.gz | docker compose exec -T postgres psql -U pareeksha -d pareeksha -v ON_ERROR_STOP=1 -q
docker compose run --rm --no-deps api python -m pareeksha.seed   # re-adds the API key from PAREEKSHA_API_KEY (idempotent for the rest)
docker compose up -d api                        # its migrate step finds alembic at head and changes nothing
python3 scripts/calibration/import_labels.py --owner-raw labelling/EVAL-06/labels.owner.csv --extra-md proof/EVAL-06/recalibration_plan.md
# L01-L10 come back 409 "already"; once the owner fills L11-L30, those 20 are posted and INTERIM disappears
```

## Tests (`pytest.txt`)

- `test_calibration_import_labels.py`: 32 passed. These are the original 15, plus 10 for pass/fail-only mode,
  plus 7 for pending rows and intervals:
  - blank rows are pending, while a row with only a note is still an error;
  - id ranges, and normalisation that blanks unreviewed rows;
  - the Wilson interval, bootstrap undefined-share, the INTERIM report and id spans.

  The 10 pass/fail-only tests cover:
  - rows without scores, and partly filled or mixed modes rejected;
  - the owner-sheet normalisation and unknown verdicts;
  - identical-row detection;
  - offline κ equal to the endpoint function, with the 2x2 table, critical agreement and disagreements;
  - "not provided by owner" in the report.
- CI test set: 991 passed, 1 failed. The failure is `test_schema_dts_fresh`, which needs `npm ci` in `web/`. It
  fails the same way on unmodified main in this sandbox.
- Backend `ruff check` and `ruff format --check` are clean.

## Spend

**DeepSeek** (token counts from the service logs and `gloss_usage.json`; prices from NOTES TL-01, peak
cache-miss list price, so this is an upper bound):

| use | model | calls | tokens in | tokens out | cost |
|---|---|---|---|---|---|
| judge (30 + the 3 street calls) | v4-pro | 33 | 107,301 | 15,439 | ≈ $0.20 |
| caller | flash | 131 | 124,011 | 8,391 | ≈ $0.05 |
| gloss (2 exports) | flash | 42 | 38,435 | 13,861 | ≈ $0.03 |

DeepSeek total: about **$0.28**.

**Gnani**, from `api_usage` for the simulator side:
- TTS: 222 requests, 12,721 characters.
- STT REST: 160 requests, 999 s.

The clean mock agent logged a further 37 TTS (287 s of audio, 4,046 characters) and 59 STT REST (233 s). The
bug containers' usage logs were removed with the containers, so they are not counted. `COST_GNANI_*` is unset
(as in VOICE-01 / EVAL-05), so the Gnani spend is in units, not dollars. The whole task is well under the $15
budget for everything that has a price.

## ISSUES (not fixed here; outside this task's scope)

- **ISSUE-1 (mock agent):** street noise at 10 dB SNR mutes the mock agent (barge-in VAD fires on the noise
  bed during opening synthesis; `mock_agent/server.py` `_on_audio`). Any run that uses `pstn_street_10db`
  against the mock agent measures this, not the dialog.
- **ISSUE-2 (simulator):** a punctuation-only caller line (the silent persona/scenario) goes to Gnani TTS,
  which returns 500 "No audio generated during synthesis". The call ends `infra_error`, so "Caller goes
  silent" cannot complete. The simulator should treat such a line as silence and not call TTS.

## Commit

Code + packet + batch evidence: `9f2a41f261b122c14f9b0388e74d8fa17f1d3579` on branch `task/EVAL-06` (base main @5ccf328).
