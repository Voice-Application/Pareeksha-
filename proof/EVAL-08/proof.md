# EVAL-08: rubric-2026-11-v3 (owner rules R-a to R-e), ISSUE-4, mypy, re-score L/H, confirmation batch C01-C15

Branch `task/EVAL-08` from `origin/task/EVAL-07` (b3ffc13). The owner approved building v3, with rules R-a to R-f
(2026-11-03). The commit SHAs are in the git log of `task/EVAL-08`: code `aaa23af`, and the final commit holds this
file.

**Status**

| | result |
|---|---|
| 1. mypy (13 errors from `rejected.md`, 14 at branch point) | **Clean**: `cd backend && mypy` gives "no issues found in 350 source files". ruff check and ruff format are clean. No ignores were added. |
| 2. ISSUE-4 (Kannada STT disclosure) | **Fixed**, with grounded spellings only. All 10 calls whose transcript has ರೆಕಾರ್ಡೆಡ್ / ರೆಕಾರ್ಡರ್ now pass. The only recording fails left are the `no_disclosure` calls (`issue4_check.txt`). |
| 3. `rubric-2026-11-v3` + `judge_v3.j2` | **Active.** v1 and v2 are unchanged. No contract change. One test group per rule (`test_rubric_v3.py`, 22 tests). |
| 4. v3 κ on L01-L30 / H01-H30 / pooled | **0.379 / 0.127 / 0.431** (pass/fail). **Both sets are SEEN**, not held-out (see below). Below the 0.6 target. |
| 5. Confirmation batch C01-C15 | 15 new real calls, 15/15 evaluated, 0 re-runs. Labelled by the owner on 2026-11-03: **confirmation κ 0.167** (agreement 9/15; critical κ 0.762). It would be 0.595 if C02/C04/C12 followed R-a (a label/rule conflict pending the owner). See `confirm_calibration.md`. |

## 1. mypy

`cd backend && mypy` (pinned mypy 2.4.1) went from 14 errors in 4 files to clean. The 13 in `rejected.md` plus one
more `cal` annotation. Each was fixed in the code:

| file | fix |
|---|---|
| `mock_agent/vad.py` | `_real_speech` slices `bytes(self._buf)` (`rms` takes `bytes`) and sums bools (`sum(rms(f) >= bar …)`). |
| `mock_agent/llm_dialog.py` | The request body is typed `dict[str, Any]` (requests' `JsonType`). |
| `tests/unit/mock_agent/test_llm_dialog.py` | `Reply = dict[str, str] \| str \| Exception` for the fake's queue, so the provider-error test passes a `RuntimeError` legitimately. `say()` returns `dict[str, str]`. |
| `tests/unit/test_calibration_import_labels.py` | `dict[str, Any]` for the judge rows and `cal` dicts, `list[dict[str, str]]` for the param. The κ expected value is asserted non-None before `round`. |

The commands, all clean: `cd backend && ruff check . && ruff format --check . && mypy`. This is `make lint`'s backend part.

## 2. ISSUE-4: STT spellings in the disclosure check

**The cause.** Kannada (and Hindi) STT write English speech in native script. "This call is being recorded" came back
as "ದಿಸ್ ಕಾಲ್ ಈಸ್ ಬೀಯಿಂಗ್ ರೆಕಾರ್ಡೆಡ್". The agent's regex `(record|ರೆಕಾರ್ಡ್|रिकॉर्ड)` needs ರೆಕಾರ್ಡ **್** (virama), so
ರೆಕಾರ್ಡ **ೆ**ಡ್ did not match.

**The fix** (`backend/pareeksha/evaluation/checks.py`, `stt_spellings.yaml`):
- A disclosure is tried on the turn as written, then on a copy where each listed STT spelling is replaced by its
  English word (longest spelling first).
- The table lists only spellings found in this repo's real transcripts, with where each was seen:

  | English | spellings |
  |---|---|
  | recorded | ರೆಕಾರ್ಡೆಡ್, ರೆಕಾರ್ಡರ್ಡ್ |
  | recorder | ರೆಕಾರ್ಡರ್ |
  | recording | रिकॉर्डिंग |
  | record | ರೆಕಾರ್ಡ್, रिकॉर्ड |
  | suraksha | ಸುರಕ್ಷಾ, सुरक्षा |

  No fuzzy transliteration is involved. A near-miss spelling never seen (e.g. ರಿಕಾರ್ಡಿಂಗ್) still fails, and there
  is a test for that. The agent's own regex is unchanged; the forbidden-phrase check is unchanged.
- **Live result** (`issue4_check.txt`, check rows recomputed under v3):
  - EVAL-06: L02, L04, L07, L21 pass.
  - EVAL-07: **H12, H17, H27, H28 pass** (the 4 false fails ISSUE-4 named).
  - EVAL-08: C02, C09 pass.
  - The only `recording` fails left are the `no_disclosure` bug calls: L05/L06/L16/L20, H02/H16/H18/H29, C04/C12.

## 3. rubric-2026-11-v3 + judge_v3.j2

| owner rule | where it is implemented |
|---|---|
| **R-a** No recording disclosure **or** no company identity → fail | The gate's `failure_types` includes `missing_disclosure` (from the judge, or from a failed `disclosure_present` check). The seed agent gained a must-pass `company` disclosure, regex `(suraksha\|ಸುರಕ್ಷಾ\|सुरक्षा)`, patched onto the 6 live agents (`agent_disclosure_patch.log`). Prompt rule 1; `policy_compliance` anchor 1. |
| **R-b** Repetition lowers the score by a point, never fails alone | `loop` was removed from the gate. `conversation_flow` 3 = "repeated the same sentence". Repetition was removed from the `empathy_tone` and `task_completion` anchors. Prompt rule 3: "costs exactly one point on conversation_flow". |
| **R-c** Amount read-back only when asked, not must-pass | `advisory_checks: [amount_confirmed]`: a failed `amount_confirmed` is stored and shown to the judge, but it is not a failed must-pass check (`scoring.finalize_scores`). Prompt rule 4. A wrong amount is still critical through the judge. |
| **R-d** A missed point fails | Gate `intent_miss`. Prompt rule 2: a caller question or request never answered later in the call, or a relevant on-file fact (due date, amount, account detail) the caller asked for and never got. Fillers ("are you there?") don't count, and an answer one turn late is not missed. `task_completion` anchor 1. |
| **R-e** Confirmation is not fabrication | Prompt rule 5. Critical list: "asserted or recorded a commitment or fact the caller never gave or confirmed". `factual_accuracy` 0 anchor. Restating a confirmed fact is never critical. v2's two extra critical rules (stopped responding, ignored 3+ times) are dropped: those are now missed points (R-d). |
| **R-f** Critical on passed calls | Pass/fail is the primary κ. Critical κ is reported separately, and calls labelled pass + critical are listed as "inconsistent labels" (L10; H15, H21, H27) and counted as written. |

**Other details.**
- **Gate.** No per-dimension gate (`max_failing_score: null`); the owner's rules name the failing conditions. The pass
  threshold stays at 80.
- **Files.**
  - `seed/data/rubric-2026-11-v3.yaml`, `llm/prompts/judge_v3.j2` (v2 prompt plus the "Owner rules" section and the
    new critical list).
  - `evaluation/rubric.py`: the `RUBRICS` registry gains v3, `RUBRIC_VERSION = rubric-2026-11-v3`, and `_from_yaml`
    loads v2 and v3.
  - `scoring.py`: `advisory_checks`. `seed/runner.py` seeds v1, v2 and v3, and makes v3 active (live DB: `v3 | t`).
- **Unchanged.** v1 (`ANCHORS_V1`, `judge_v1.j2`) and v2 (`rubric-2026-10-v2.yaml`, `judge_v2.j2`) are unchanged.
  v2's tests still pass against `RUBRICS[RUBRIC_V2]`.
- **No contract change.**
  - No new `FailureType`: missed points use `intent_miss`, fabrication uses `wrong_fact`.
  - The OpenAPI test `test_schema_dts_fresh` passes.
  - One contract constraint was worked around: `within_turns` is `int >= 1`, default 2, and `null` is rejected.
    "Never says the company" therefore uses `within_turns: 100`, i.e. the whole call (calls end at 240 s).
  - First draft: the company check briefly ran with `within_turns: 2`. 7 L/H calls whose check ran under that
    draft were re-judged after the change (`rejudge_company.py`, `rejudge_company.log`). Under the final rule,
    L28 says the company in agent turn 3 and passes the check.
- **Tests.** `backend/tests/unit/evaluation/test_rubric_v3.py` has 22 tests:
  - the version and YAML;
  - R-a: judge tag, failed check (recording / company), the seeded agent needs both, company anywhere in the call;
  - ISSUE-4: 3 Kannada STT forms, Hindi and English, grounded-not-fuzzy;
  - R-b: loop tag alone passes, failed `no_loop` passes, anchor is one point;
  - R-c: `amount_confirmed` is advisory in v3 and still must-pass in v2;
  - R-d: `intent_miss` fails;
  - R-e: fabricated commitment is critical;
  - the rendered prompt carries each rule.
- **Updated tests.** `test_rubric_v2.py` (v2 is kept rather than active), `test_judge_evaluator.py` (amount
  check advisory under v3), `tests/integration/test_seed.py` (v1+v2+v3 seeded, v3 active).

## 4. v3 on the 60 labelled calls: SEEN, not held-out

**Both sets are SEEN.** L01-L30 labels shaped v1, v2 and the rules. H01-H30 were v2's held-out test, but the owner's
H labels and notes (H05, H09, H13, H21, the 4 passed `no_disclosure` calls) are what R-a to R-e answer. Neither set
can show whether v3 generalises; the confirmation batch (section 5) is the test.

**What ran.** No new speech.
- `reevaluate.py` added a v3 evaluation row per call; the v1 and v2 rows are kept.
- The owner's existing labels were posted against the v3 rows through `POST /calls/{id}/review` (60 × 201), and
  read back from `GET /calibration`.

```
python3 scripts/calibration/patch_agent_disclosures.py                    # agent_disclosure_patch.log
python3 scripts/calibration/reevaluate.py --batch proof/EVAL-06/batch.json --rubric rubric-2026-11-v3          # 30/30, 236 s
python3 scripts/calibration/reevaluate.py --batch proof/EVAL-07/heldout_batch.json --rubric rubric-2026-11-v3  # 30/30, 227 s
python3 scripts/calibration/rejudge_company.py proof/EVAL-06/batch.json proof/EVAL-07/heldout_batch.json       # 7/7
python3 scripts/calibration/export_judge_results.py --batch proof/EVAL-06/batch.json --rubric-version rubric-2026-11-v3 --out proof/EVAL-08/judge_results_v3_L.json
python3 scripts/calibration/export_judge_results.py --batch proof/EVAL-07/heldout_batch.json --rubric-version rubric-2026-11-v3 --out proof/EVAL-08/judge_results_v3_H.json
python  scripts/calibration/import_labels.py --labels labelling/EVAL-06/labels.csv --key labelling/EVAL-06/.key.json \
        --judge proof/EVAL-08/judge_results_v3_L.json --out proof/EVAL-08/seen_L --expect-n 30 --note "SEEN ..."
python  scripts/calibration/import_labels.py --labels labelling/EVAL-07/labels.csv --key labelling/EVAL-07/.key.json \
        --judge proof/EVAL-08/judge_results_v3_H.json --out proof/EVAL-08/seen_H --api-pooled --expect-n 60 --note "SEEN ..."
```

| set (n) | v3 κ pass/fail | agreement | judge / owner passes | v3 κ critical | earlier rubric (pass/fail κ) |
|---|---|---|---|---|---|
| L01-L30 (30), SEEN | **0.379** (bootstrap 95% CI [−0.09, 0.76]) | 24/30 | 7 / 5 | 0.186 (judge 4, owner 18) | v1 0.189 · v2 0.609 (in-sample) |
| H01-H30 (30), SEEN | **0.127** (CI [−0.21, 0.47]) | 19/30 | 19 / 24 | 0.468 (judge 3, owner 8) | v2 0.000 (held-out) |
| pooled (60), SEEN | **0.431** (`GET /calibration` n = 60, matches the offline recompute) | 43/60 | 26 / 29 | 0.295 | — |

Details: `seen_L/calibration.md`, `seen_H/calibration.md`, `pooled_kappa.txt`.

**What the disagreements show** (pass/fail; nothing was tuned on them):
- **H: 6 of the 8 judge-fail / owner-pass calls fail under R-a** (H02, H16, H18, H29 lack the recording disclosure;
  H15 and H26 never say the company because the caller barged into the opening and the agent skipped its greeting).
  The owner passed them on 2026-11-02, before R-a existed. Under the owner's own new rule these are fails, so they
  are a conflict between the old labels and R-a, not a judge error.
  - The other two are H01 and H11 (`intent_miss`).
- **L: 6 disagreements.**
  - L13, L26: judge fail (`intent_miss`), owner pass.
  - L02, L14, L22, L30: judge pass, owner fail.
    - L02: owner note "speaking in English not in Kannada" (judge language_handling 1, score 83.75).
    - L14: late transfer.
    - L22: "not responding to what the user is asking".
  - In-sample v2 matched L better because its loop and dimension gates matched how the owner labelled the
    scripted agent then; R-b removes those gates.
- **R-e did not catch H09** (v3 judge passed it, 100). The owner failed it because the agent confirmed a payment on
  the 5th that the caller never committed to. Rule 5 in the prompt did not make the judge flag it.
- **Critical:** the owner marks far more calls critical (L: 18 of 30) than v3's critical list allows (4). Per R-f
  this is reported separately and not used for pass/fail.

## 5. Confirmation batch C01-C15 (new real calls, final VAD, v3)

```
python3 -u scripts/calibration/run_batch.py --use confirm      # confirm_run.log, confirm_batch.json ("evaluated 15/15", exit 0)
python3 scripts/calibration/export_judge_results.py --batch proof/EVAL-08/confirm_batch.json --rubric-version rubric-2026-11-v3 --out proof/EVAL-08/confirm_judge_results.json
SSL_CERT_FILE=/root/.ccr/ca-bundle.crt python scripts/calibration/export_packet.py --batch proof/EVAL-08/confirm_batch.json \
        --packet labelling/EVAL-08 --proof proof/EVAL-08 --prefix C --title "EVAL-08 confirmation" --bitrate 32k --count 15
```

**Mix.**
- Same as EVAL-06/07: 5 clean + 2 per planted bug.
- 8 kn / 4 hi / 3 en; noise 7 `pstn_8k_alaw`, 4 `pstn_office_babble_15db`, 4 `clean_16k`.
- No cell repeats an EVAL-06 or EVAL-07 cell (asserted in `run_batch.py`). "Caller goes silent" stays out (ISSUE-2).

**Fresh seeds.** Every run had a new random `config.seed`, stored as `run_seed` in `confirm_batch.json`. Earlier
batches all ran with the API default, 42 (NOTES).

**Agent.** The mock-agent image was built from this branch, so it has the final VAD from EVAL-07, plus the LLM
dialog and bug containers. 15/15 calls `evaluated`, no infra errors, no replaced calls.

**Judge v3** (`confirm_judge_results.json`, kept **outside** the packet).
- Overall: 8/15 pass, 2 critical (both `false_waiver`).
- By group:

  | group | pass |
  |---|---|
  | clean | 4/5 |
  | `no_disclosure` | 0/2 (R-a) |
  | `no_amount_confirm` | 1/2 |
  | `english_to_kannada` | 1/2 |
  | `ignore_interrupt` | 2/2 |
  | `false_waiver` | 0/2 (critical) |
- C02 (`english_to_kannada`) fails R-a on the company name. Its recording disclosure **passes** through the new
  spelling table ("ರೆಕಾರ್ಡೆಡ್").

**Packet** `labelling/EVAL-08/` (EVAL-07 format, 5.3 MB).
- Contents:
  - `index.html`, `C01.html`-`C15.html`;
  - `audio/C01.mp3`-`C15.mp3` (32 kb/s);
  - `labels.csv` template, `.key.json` (shuffle seed 508266647);
  - `GUIDE.md` for **v3**: the owner's rules R-a to R-e, the v3 anchors copied from the YAML, the v3 critical list,
    and the R-f note.
- **Blindness check (scripted):** no bug name, scenario title, persona, noise profile, call or run id, agent name,
  rubric version or `gate:` string on any page. The one hit, "judge", is the index's generic sentence "Nothing
  here shows how the automatic judge scored a call", as in EVAL-07.

**Confirmation κ (owner labels 2026-11-03, `confirm_calibration.md`).**
- The owner's JSON is saved verbatim as `labelling/EVAL-08/labels.owner.json` and was written into `labels.csv` with
  `--fill-json`.
- The import posted 15 reviews through the API (15 × 201); `GET /calibration` n = 75 (pooled guard 60 → 75).
```
python scripts/calibration/import_labels.py --labels labelling/EVAL-08/labels.csv --key labelling/EVAL-08/.key.json \
    --judge proof/EVAL-08/confirm_judge_results.json --out proof/EVAL-08/confirm --api-pooled --expect-n 75 --fill-json labelling/EVAL-08/labels.owner.json
python scripts/calibration/import_labels.py ... (same, without --fill-json)    # import_confirm.log
```
- **Pass/fail:** κ **0.167** (bootstrap 95% CI [−0.25, 0.59]), agreement 9/15; v3 passes 8, owner 12.
- **Critical:** κ **0.762**, agreement 14/15.
- **C02, C04, C12** fail under the owner's own rule R-a, and the owner passed them (`confirm_facts.txt`: C02 never
  names the company; C04 and C12 never say the call is recorded). This is a label/rule conflict pending the owner,
  not a judge error. If they followed R-a, κ would be 0.595 (12/15).
- **Real judge misses:**
  - C11: "I don't have that information" was tagged `intent_miss`.
  - C13: an immediate requested transfer was scored as task failure.
  - C14: passed although the agent transferred without asking for the UTR; the owner failed it and marked it
    critical.
- v3 was not tuned on this set. n = 15 is below V9's minimum of 30.

## Tests (`pytest.txt`)

- `cd backend && python -m pytest tests/unit tests/evaluation tests/judge tests/contract -q`: **1106 passed, 0
  failed**. That is 1105 plus `test_schema_dts_fresh` after `npm ci` in `web/`; before `npm ci` it fails only for
  the missing `node_modules`.
- `tests/integration/test_seed.py`: 11 passed, 1 failed (`pytest_seed.txt`).
  - The failure, `test_an_existing_active_rubric_is_not_replaced`, **pre-dates this branch**. It fails the same way
    with this branch's changes stashed.
  - EVAL-07's seed always switches to the build's rubric, and the test still expects a custom active rubric to be
    kept. Not changed here (ISSUE-7).
- Lint: `ruff check .`, `ruff format --check .`, `mypy` are all clean (section 1).

## Spend (this session, `api_usage_eval08.txt`)

| provider | use | requests | units |
|---|---|---|---|
| DeepSeek | judge (60 re-scores + 7 company re-judges + 15 confirmation + retries) | 83 | 419,228 tokens |
| DeepSeek | caller LLM | 48 | 48,988 tokens |
| Gnani | STT / TTS (simulator side) | 77 / 94 | 473 s / 5,115 chars |

- At EVAL-07's rate (≈ $0.57 per 354k judge tokens, an upper bound), that is ≈ **$0.70** for the judge and caller.
- Mock agent LLM and gloss come to a few cents more.
- **Total < $1**, well under the $10 budget. Gnani has no price set.

## Database dump

`pareeksha_db.sql.gz` is a `pg_dump` after the confirmation labels were imported (75 v3 reviews). It holds every table except the rows of
`api_keys`: the 87 earlier calls plus the 15 C calls, and v1/v2/v3 evaluations. Restore it as in
`proof/EVAL-06/proof.md`.

## ISSUES

- **ISSUE-6 (agent behaviour, observed):** when the caller talks over the opening, the mock agent replays the
  recording disclosure but drops its greeting, so the company name is never said. Seen in L01, L04, L23, H15, H26
  and C02. Under R-a these calls fail. This is a real defect of the mock agent, not of the judge.
- **ISSUE-7:** `test_seed.py::test_an_existing_active_rubric_is_not_replaced` has failed since EVAL-07 (see Tests).
  It needs a decision on whether a custom active rubric survives a seed.
- Still open: ISSUE-A (no rubric version on `call.completed`), ISSUE-2 (silent caller TTS 500), ISSUE-3 (Gnani STT
  504s mute the agent), ISSUE-5 (`GET /calibration` has no batch filter).
- **Owner question:** H02, H16, H18, H29 (no recording disclosure) and H15, H26 (no company name) were passed on
  2026-11-02. Under R-a they fail. Should those labels be read under R-a? Nothing here relabels them.
