# EVAL-06 (prep half): 30 real calls + blind labelling packet + label importer

GOAL item 9 / V9: judge vs Preetham's labels on 30 calls, Cohen's kappa. Spec: docs/08-evaluation-rubric.md
§2 (rubric-2026-10-v1) and §10 (calibration: human labels blind to the judge), docs/02-requirements.md
FR-EV-8, `GET /api/v1/calibration` (backend/pareeksha/api/routers/system.py), `POST /api/v1/calls/{id}/review`
(backend/pareeksha/api/routers/calls.py → `human_reviews`).

**Status**
- Built and run: real 30-call batch (all 30 evaluated by the judge), blind packet, importer and its unit tests.
- **Kappa / Spearman / MAE: BLOCKED ON OWNER LABELS.** `labelling/EVAL-06/labels.csv` is an empty template. I
  did not fill it in. `proof/EVAL-06/calibration.json` / `calibration.md` do not exist yet; the importer writes
  them once the owner has labelled the calls.
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

## After the owner labels (V9)

```
python3 scripts/calibration/import_labels.py            # reviewer "preetham"; validates, POSTs 30 reviews, GET /calibration
# -> proof/EVAL-06/calibration.json, calibration.md ; then: make verify-step N=9
```
- On the current empty template the importer refuses and posts nothing: exit 2, with every missing value
  listed (`import_labels_empty_template.txt`).
- A row the API already holds for this reviewer (409) is counted as "already" and left unchanged.
- **Expected output**: `n = 30` plus kappa, Spearman and per-dimension MAE from the API, and the disagreement
  table (pass/fail or critical differ, or a dimension differs by 2 or more).
- The importer has **not** been run against the API, because that would need labels.
- **Caveat:** the 30 calls and their evaluations live in this session's Compose Postgres (`pg-data` volume)
  in an ephemeral cloud container. The import needs a database that holds these call ids, so either keep or
  dump that database (`docker compose exec postgres pg_dump -U pareeksha pareeksha`), or regenerate the batch
  and packet (`run_batch.py` + `export_packet.py`) on the stack where the labels will be imported. The
  committed `judge_results.json` keeps the judge's verdicts in either case.

## Tests (`pytest.txt`)

- `test_calibration_import_labels.py`: 15 passed.
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
