# DIALECT-02 proof: dialect report on Vaani clips (GOAL item 7)

Branch `task/DIALECT-02` from `main` @ 5ccf328. Commit SHA: see "Commit" at the end. Contracts untouched
(no API, event, DB or schema change; the run uses the existing Dialect API and `dialect` worker).

Owner decision 2026-10-30: the data comes from **Vaani** (`ARTPARK-IISc/Vaani`, CC-BY-4.0, gated),
not from self-recorded clips. Recorded in `CHANGELOG.md`.

## Built

| File | What |
|---|---|
| `scripts/data/fetch_vaani.py` | Streams Vaani parquet shards over HTTP range requests (`HfFileSystem` + `pyarrow`): reads only the text columns of a shard to choose clips, then the `audio` column of only the row groups holding chosen clips. Selection, tag stripping, speaker ids and docs as described in `data/dialect/vaani/SOURCES.md`. Pinned to dataset commit `9e6ed4f9`. `--docs-only` rebuilds SOURCES.md / REVIEW.md offline. |
| `data/dialect/vaani/<group>/*.wav` | 110 clips, 16 kHz mono 16-bit WAV, 30 MB in total |
| `data/dialect/vaani/manifest.csv` | `file, reference_text, language, dialect_label, speaker_id, consent, domain_terms` |
| `data/dialect/vaani/SOURCES.md` | dataset, licence and attribution, citation, groups and districts, selection rules, the transcription convention and how each tag was stripped, every clip's Vaani row id (file name, shard, row index), the fetch log |
| `data/dialect/vaani/sources.json`, `fetch_log.txt` | per-clip raw Vaani transcript, district, gender, duration; shard scan log |
| `data/dialect/vaani/REVIEW.md` | 5 clips per group (path + reference text) for the owner's accent and transcript spot-check |
| `backend/tests/unit/dialect/test_fetch_vaani.py` | 15 tests: tag stripping on real Vaani transcripts, English-gloss detection, eligibility rules, code-mix rule, speaker ids, speaker de-duplication + round-robin, WAV conversion accepted by the manifest importer, committed manifest rows valid |
| `proof/DIALECT-02/live_run.py` | acceptance driver against the Compose API (`--collect` re-reads the outputs without new STT calls) |

### Groups (n per group)

| group | source districts | clips | speakers | audio |
|---|---|---|---|---|
| kn-mysuru | Mysore 16, Chamarajanagar 6 | 22 | 22 | 190 s |
| kn-north | Dharwad 21, Belgaum 1 | 22 | 22 | 205 s |
| kn-coastal | Dakshina Kannada 22 | 22 | 22 | 244 s |
| hi-standard | New Delhi 22 (Lucknow scanned first: its shard 0 has 1 transcribed row, not eligible) | 22 | 17 | 154 s |
| kn-en-mix | Bangalore 22, transcript marks >= 2 English words making up >= 10 % of the words | 22 | 22 | 154 s |

kn-en-mix had more than enough genuinely mixed clips (309 eligible in the first Bangalore shard), so
nothing was padded. All clips are 5-20 s (hi-standard 5-9 s: Delhi rows are mostly short).

Decisions (R4 findings in `NOTES.md`):
- `speakerID` is empty for most rows; the speaker id is the token after the district in the Vaani
  file name (`speakerID == "SID_<token>"` wherever both exist; the script raises if they disagree).
- Different ids with identical (district, gender, pincode, stay) exist (33 in Dharwad/Belgaum, 53 in
  Bangalore), so only one id per such cluster is used; ids with conflicting gender would be dropped.
  Clips are taken round-robin across speakers (max 4 each), so most groups have one clip per speaker.
- Clips whose transcript has `[unintelligible]`, `[inaudible]` or `<UNKNOWN_SEGMENT>` are excluded
  (an incomplete reference would charge the engine for words nobody wrote down).
- References keep Vaani's verbatim native-script spelling, English loanwords in native script.
  `consent=true` records Vaani's dataset-level signed consent (paper section 5), not ours.
- The dialect label is the speaker's district of residence, not a linguist's accent judgement.

## Reproduce

```
# data (needs HF_TOKEN with Vaani access; ~3.5 min, reads ~1 GB of row groups, writes 30 MB)
python3 -m venv /root/venv-d2 && /root/venv-d2/bin/pip install -U pip setuptools
/root/venv-d2/bin/pip install -r requirements.txt -e backend -r backend/requirements-dev.txt pyarrow huggingface_hub
/root/venv-d2/bin/python scripts/data/fetch_vaani.py --out data/dialect/vaani

# stack (sandbox: TLS proxy overlay; Docker Hub returned 429, images pulled from mirror.gcr.io and re-tagged)
export CA_BUNDLE=/root/.ccr/ca-bundle.crt BUILDX_BAKE_ENTITLEMENTS_FS=0
docker compose -p dialect02 -f docker-compose.yml -f docker-compose.proxy.yml -f keys.yml \
    --profile workers up -d --build api outbox-relay dialect retrier dlq-recorder
#   keys.yml (not committed) only passes GNANI_API_KEY and DEEPSEEK_API_KEY from the shell to api + dialect:
#   services: {api: {environment: {GNANI_API_KEY: ${GNANI_API_KEY:?}, DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:?}}}, dialect: (same)}

# run (real Dialect API: CSV manifest + clips ZIP upload, evaluate, poll, export)
PYTHONPATH=backend /root/venv-d2/bin/python proof/DIALECT-02/live_run.py > proof/DIALECT-02/live_run.txt
for s in api dialect outbox-relay retrier dlq-recorder; do docker compose -p dialect02 logs --no-color $s > proof/DIALECT-02/$s.log; done

# tests and lint
cd backend && python -m pytest tests/unit tests/evaluation tests/judge tests/contract -q -p no:cacheprovider
ruff check . && ruff format --check . && ruff check ../scripts/data ../proof/DIALECT-02 && python -m mypy
```

Expected: upload `accepted 110, rejected []`, `expected_results 330`, progress to 330/330, a report
with one cell per group x condition, each with n=22 and a speaker-bootstrap CI.

## Results

### Live run (`live_run.txt`, `report.json`, `report.html`, `clips.json`, `usage.json`, `*.log`)
Compose stack: Kafka, Postgres (Alembic-migrated by `migrate`), `api`, `outbox-relay`, `dialect`
(one consumer, `max_records=1`, so one Gnani request at a time), `retrier`, `dlq-recorder`. Real
Gnani Prisma STT (`stt_rest`) and real DeepSeek (`deepseek-v4-pro`, intent flag). 110 clips x 3
conditions = 330 results; the report completed 1,293 s after `evaluate`. DB check (`usage.json`):
110/110 samples consented, 330 `asr_results`, 330 `dialect.clip.requested` events processed, DLQ
empty (`dlq-recorder.log` empty, `retrier.log` empty).

Gnani WER (pooled, 95% CI from the speaker-grouped bootstrap), CER, entity accuracy, intent preserved; n = 22 clips in every cell:

| group | condition | speakers | WER [95% CI] | CER | entity acc | intent |
|---|---|---|---|---|---|---|
| hi-standard | clean_16k | 17 | 6.8% [3.9, 10.3] | 2.3% | 97% | 100% |
| hi-standard | pstn_8k_alaw | 17 | 6.8% [4.4, 10.0] | 2.4% | 97% | 100% |
| hi-standard | pstn_street_10db | 17 | 10.4% [8.0, 13.2] | 4.8% | 97% | 86% |
| kn-en-mix | clean_16k | 22 | 28.3% [22.1, 34.8] | 6.4% | 75% | 95% |
| kn-en-mix | pstn_8k_alaw | 22 | 26.0% [19.8, 32.6] | 6.4% | 78% | 91% |
| kn-en-mix | pstn_street_10db | 22 | 30.6% [24.0, 37.2] | 9.1% | 74% | 91% |
| kn-coastal | clean_16k | 22 | 33.8% [28.2, 38.7] | 9.4% | 88% | 100% |
| kn-coastal | pstn_8k_alaw | 22 | 34.3% [29.1, 38.4] | 10.0% | 82% | 95% |
| kn-coastal | pstn_street_10db | 22 | 41.8% [34.1, 48.7] | 14.2% | 71% | 82% |
| kn-mysuru | clean_16k | 22 | 50.6% [41.1, 59.5] | 22.8% | 77% | 91% |
| kn-mysuru | pstn_8k_alaw | 22 | 52.3% [43.3, 61.1] | 24.1% | 77% | 77% |
| kn-mysuru | pstn_street_10db | 22 | 58.7% [49.6, 67.7] | 28.4% | 77% | 45% |
| kn-north | clean_16k | 22 | 60.9% [51.8, 69.7] | 22.3% | 100% | 95% |
| kn-north | pstn_8k_alaw | 22 | 61.8% [53.4, 69.8] | 23.3% | 100% | 91% |
| kn-north | pstn_street_10db | 22 | 64.0% [54.6, 72.5] | 29.0% | 100% | 73% |

How to read this honestly:
- **Much of the Kannada WER is spelling convention, not mishearing.** Vaani references are
  verbatim colloquial spellings; Prisma writes standard forms. The top "errors" are `ತುಂಬಾ->ತುಂಬ`
  x21, `ಅಂದ್ರೆ->ಅಂದರೆ` x14, `ಎಲ್ಲಾ->ಎಲ್ಲ` x12, `ಇದಾರೆ->ಇದ್ದಾರೆ` x9; kn-north references such as
  `ಅದ್ ನೋಡಾಕ್ ಎಷ್ಟ್ ಚನಗ್` come back as `ಅದು ನೋಡಕ್ಕೆ ಎಷ್ಟು ಚೆಂದ` (same words, standard spelling). CER
  (22-29 % for kn-north / kn-mysuru) is the fairer comparison; intent is preserved for 91-95 % of
  clean clips in both. The normaliser's loanword / variant table (`loanwords.yaml`) does not cover
  colloquial Kannada verb and particle forms; adding them is a follow-up, not done here.
- kn-north and kn-mysuru are worse than kn-coastal and kn-en-mix on both WER and CER with
  non-overlapping CIs on clean audio; whether that is accent or the transcribers' more phonetic
  spelling in those districts cannot be separated with this data.
- hi-standard is clearly the easiest (WER 7 %), consistent with Hindi transcripts that are closer to
  standard spelling.
- Street noise at 10 dB SNR costs 2-8 WER points and sharply lowers intent preservation for
  kn-mysuru (91 % -> 45 %); 8 kHz A-law alone changes little.
- Entity accuracy counts numbers (spoken numerals, normalised) everywhere and, for kn-en-mix only,
  the English loanwords as domain terms. kn-north's 100 % is 7 of 7 number words on clean audio
  (kn-mysuru 10/13, kn-coastal 15/17, hi-standard 30/31, kn-en-mix 54/72), not a strong entity test. Suggested `bias_list`: `ಎಕ್ಸಿಟ್, ಗ್ಯಾರೇಜ್, ಇನಾಗ್ರೇಷನ್, ಎಕ್ಸರ್ಸೈಜ್, ಫ್ಲಾಗ್, ಡಿಸೈನ್, ಬೋರ್ಡ್, ...`
  (kn-en-mix loanwords Prisma missed).
- These are image-description monologues, not EMI collection calls; the report says nothing about
  domain vocabulary such as EMI / NEFT.

Gnani returned HTTP 429 88 times during the run (JSON `error` lines of logger `gnani` in
`dialect.log`; the only other `error` line is aiokafka's `GroupCoordinatorNotAvailableError` at start-up) even though this stack sends one
request at a time: the key allows one active request and is presumably shared with other sessions.
`gnani/clients.py` retried each 429; every one of the 330 clips finished, none went to the DLQ.

### Usage and cost (`usage.json`, from `api_usage`)

| provider | operation | calls | units |
|---|---|---|---|
| Gnani | `stt_rest` (Prisma) | 330 | 2,840.9 s of audio (47.3 min) |
| DeepSeek | `llm_asr_intent` (`deepseek-v4-pro`, only clips whose normalised text differs) | 300 | 138,158 tokens |

`COST_*` rates are not set, so `est_cost` is NULL. Gnani publishes no per-minute price (searched
2026-10-30); at an assumed ceiling of $0.05 / min that is <= $2.37. DeepSeek: 138 k tokens, about
$0.30 even at an assumed $2 / M tokens. Upper-bound estimate: **< $3**, within the $10 budget. The
Vaani download (Hugging Face) is free. One run only; no repeated STT spend (`--collect` only re-reads).

### Tests and lint (`pytest.txt`, `lint.txt`)
`tests/unit tests/evaluation tests/judge tests/contract`: **991 passed, 1 failed** on the first run.
The failure was `tests/contract/test_schema_dts_fresh.py` asking for `npm ci` in `web/`
(environment); after `npm ci` it passes (appended to `pytest.txt`). 0 skipped. New tests: 15 in
`test_fetch_vaani.py`.
`ruff check` / `ruff format --check` clean for `backend/`, `scripts/data/`, `proof/DIALECT-02/`.
`mypy`: no error in changed files; 5 errors remain in files this task did not touch
(`mock_agent/policy.py`, `tests/unit/speech/test_deepgram.py`) with the mypy/typeshed versions this
venv resolved (`mypy>=1.10` is unpinned); see `lint.txt`.

## Not covered / follow-ups
- Integration tests (`tests/integration`, need Kafka/Postgres env vars) were not re-run; no backend
  code changed. The live run exercises the same path end to end.
- Dialect labels are districts of residence; nobody listened to the clips (owner spot-check:
  `data/dialect/vaani/REVIEW.md`).
- Colloquial Kannada spelling variants inflate WER (see above); extending normalisation is a
  separate task (it would change the frozen metric behaviour, so it needs a decision).
- `hi-en-mix` (suggested in rubric section 9.1) was not requested and is not built.
- No comparator engine (FR-DI-5) was run.

## Commit
Built, run and measured at commit `16d9e6e` (`git log task/DIALECT-02`); the following commit only
adds this SHA line.
