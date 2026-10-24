# EVAL-05 proof: dialect pipeline (manifest, WER/CER, entity accuracy, intent, speaker-grouped bootstrap, HTML report)

Branch `task/EVAL-05` from `integrate/M2` @ 71a1022. Commit SHA: the last commit of `git log task/EVAL-05` (a commit cannot contain its own hash). Contracts untouched (`docs/contracts.md`, `events/schemas.py`, `schemas/dialect.py`).
Dependency EVAL-03: present on `integrate/M2` (merged). H-02 (consented real clips) is not done, so the live run below uses **synthetic Gnani TTS voices**; groups are labelled `*-synth` and make no dialect claim. The V7 acceptance (>= 5 real groups, n >= 20) waits on H-02; the pipeline and report are ready for it.

## Built

| Module | Role |
|---|---|
| `backend/pareeksha/dialect/normalize.py` + `loanwords.yaml` | NFC, zero-width removal, digits of any script to ASCII, spoken numbers incl. lakh / crore via `evaluation.numbers`, punctuation stripped (vowel signs kept), Devanagari nukta / chandrabindu, Kannada archaic letters, loanwords and spelling variants unified to one token (data file, edit to extend) |
| `dialect/metrics.py` | Levenshtein alignment (substitutions / deletions / insertions), WER, CER (spaces ignored), entity accuracy: numbers and amounts by value, domain terms and names as whole-word phrases |
| `dialect/stats.py` | pooled ratio and **speaker-grouped percentile bootstrap** (resample speakers with replacement, 2000 resamples, seeded) |
| `dialect/manifest.py` | CSV + ZIP import, `consent` must be an explicit yes, per-row rejections with reasons, ZIP-slip safe, 16-bit WAV <= 60 s / 10 MB |
| `dialect/intent.py` + `llm/prompts/asr_intent_v1.j2` | LLM "intent preserved" flag (DeepSeek default via `LLMClient`, temp 0, pinned judge model); no call when texts are identical; null without an LLM |
| `dialect/report.py` | aggregation per dialect x condition x engine (n, speakers, WER + CI, CER + CI, entity accuracy, intent rate), top misrecognised words, `bias_list` suggestions (domain terms missed >= 2x, then reference words wrong >= 3x), standalone dark-mode-aware HTML (heatmap per metric and engine) |
| `dialect/pipeline.py` + `workers/dialect.py` | the `dialect` consumer: degrade the clip with the production `LineSimulator` (seed = uuid5(sample, condition)), transcribe, normalise, score, write `asr_results` + `api_usage`; when the report has all results it aggregates once (row lock), writes `html_path` |
| `api/routers/dialect.py`, `api/outbox.py` | the 8 `STUB(EVAL-05)` handlers replaced: create / list datasets, manifest + ZIP upload, evaluate (writes report row + one outbox `dialect.clip.requested` per clip x condition), list / get reports with progress, worst-clips drill-down, HTML (rebuilt from the DB if the file is not on the API's volume) |

Engines are named `<speech-provider>-<model>` (`gnani-prisma`, `deepgram-nova-3`, ...): any provider in `speech/registry.py` can be added as a comparator column (FR-DI-5), unknown prefixes are rejected with 400.

Decisions (all additive): `dialect_reports` has no progress columns, so the row keeps `_meta` (expected count, frozen sample ids, `complete`) inside `aggregates`, hidden from the API; intent is null for every clip when no LLM key is configured (no partial "yes" bias); a clip the engine rejects permanently goes to the DLQ and the report stays incomplete (visible on the DLQ page, replayable).

## Reproduce

```
docker compose up -d kafka postgres && docker compose up kafka-init        # or any Kafka + Postgres
pip install -r requirements.txt -r backend/requirements-dev.txt
cd backend && python3 -m pytest -p no:cacheprovider --cov=pareeksha -rs      # see pytest.txt
ruff check . && ruff format --check . && python3 -m mypy                     # lint.txt
cd .. && KAFKA=localhost:9094 PG=postgresql://pareeksha:pareeksha@localhost:5432 \
   python3 proof/EVAL-05/live_run.py                                         # needs GNANI_API_KEY, DEEPSEEK_API_KEY
```
`INFRA_TEST_KAFKA_BOOTSTRAP` / `INFRA_TEST_DATABASE_URL` / `TEST_DATABASE_URL` as in `proof/INFRA-02/proof.md`.

## Results

### Tests (`pytest.txt`, `lint.txt`)
`870 passed, 0 failed, 0 skipped` (8 min 52 s, includes INFRA-02's real 30 s / 5 min delay test), total coverage **97 %** (`dialect/` 94-100 %, `workers/dialect.py` 89 %: start-up wiring). `ruff check`, `ruff format --check` and `mypy` (strict) clean.

New tests map to TEST_PLAN: `tests/unit/dialect/test_manifest_consent.py` (FR-DI-1, NFR-9), `test_asr_metrics.py` (FR-DI-3), `test_bootstrap_ci.py` (FR-DI-4 incl. HTML render), `test_bias_list.py` (FR-DI-6), `test_intent_and_worker.py`, `tests/integration/test_dialect_pipeline.py` (API + real Postgres + the production consumer handler: consent rejection end to end, evaluate -> outbox -> handler -> report, redelivery adds nothing, retry / DLQ classification, cross-project 404s, drill-down paging) and `test_dialect_comparator.py` (FR-DI-5). Only the speech engine and the LLM are doubles there.

### Live run (`live_run.txt`, `report.json`, `report.html`, `clips.json`, `usage.json`, `*.log`)
Real Kafka (single broker), real Postgres (Alembic-migrated), uvicorn API, `outbox_relay` and `dialect` worker processes, **real Gnani STT** and **real DeepSeek** intent checks. 12 synthetic clips (3 groups x 2 speakers x 2 sentences) x 3 conditions (`clean_16k`, `pstn_8k_alaw`, `pstn_street_10db`) = 36 results; the report completed 50 s after `evaluate` (`live_run.txt`).

| dialect group | condition | n | WER (95% CI, speaker bootstrap) | CER | entity acc | intent preserved |
|---|---|---|---|---|---|---|
| hi-synth | clean_16k | 4 | 13.0% [0.0, 23.1] | 4.7% | 83% | 100% |
| hi-synth | pstn_8k_alaw | 4 | 13.0% [0.0, 23.1] | 4.7% | 83% | 100% |
| hi-synth | pstn_street_10db | 4 | 17.4% [10.0, 23.1] | 10.4% | 83% | 100% |
| kn-synth-f | clean_16k | 4 | 0.0% [0.0, 0.0] | 0.0% | 100% | 100% |
| kn-synth-f | pstn_8k_alaw | 4 | 0.0% [0.0, 0.0] | 0.0% | 100% | 100% |
| kn-synth-f | pstn_street_10db | 4 | 0.0% [0.0, 0.0] | 0.0% | 100% | 100% |
| kn-synth-m | clean_16k | 4 | 15.0% [0.0, 27.3] | 4.5% | 86% | 100% |
| kn-synth-m | pstn_8k_alaw | 4 | 15.0% [0.0, 27.3] | 4.5% | 86% | 100% |
| kn-synth-m | pstn_street_10db | 4 | 15.0% [0.0, 27.3] | 4.5% | 86% | 100% |

Top misrecognised words: `emi` heard as `आई` x3; `emi` heard as `ಐ` x3; `rupees` heard as `रूपए` x1. Suggested bias_list: `emi`.
Not a dialect finding: the sentences are synthetic TTS. The wiring evidence is: 36 `dialect.clip.requested` events consumed (`processed_events`), 36 `asr_results`, 12/12 samples consented, `api_usage` = 36 Gnani STT calls + 7 DeepSeek calls (identical-text clips skipped the LLM). The one `error` line in `dialect_worker.log` is aiokafka's `GroupCoordinatorNotAvailableError` while the broker elected the group coordinator at start-up.
Cost: `credit_use.md`.

## Not covered / follow-ups
- Real dialect data (H-02) and the V7 check (>= 5 groups, n >= 20, CI on every cell) are pending; `report.html` already renders n, speakers and CI on every cell.
- The heatmap web page is FE-05; the HTML report here is the standalone export.
- Only 16-bit WAV clips are imported (MP3 / M4A recordings must be converted first).
- FR-DI-5 is built through the provider abstraction and tested with doubles; no live comparator engine was run (Deepgram / Google keys not exercised here).
