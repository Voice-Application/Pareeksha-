# EVAL-07: rubric v2 + judge v2, responsive mock agent, VAD fix, in-sample κ, held-out packet

The owner approved the EVAL-06 recalibration plan ("YES FOR CALIBRATION", 2026-11-02, relayed by the
orchestrator) and confirmed scope A-D in this session. Branch `task/EVAL-07` = `origin/main` (81ae8f7) with
`task/EVAL-06` (7d347ba) merged in.

**Status**

| | result |
|---|---|
| A. `rubric-2026-10-v2` + `judge_v2.j2` | **Active.** v1 is kept as is; no API or DB contract changed. |
| B. Mock agent | **LLM-driven** (DeepSeek) and grounded on its facts on file. The 5 planted bugs still work: V4 **PASS**, 4/5 caught, control 2/2. |
| C. ISSUE-1 (agent muted by noise) | **Fixed** (VAD noise floor). A live babble call now gets answers. |
| D1. In-sample κ (v2 on the 30 labelled EVAL-06 calls) | **0.6087**, versus 0.1892 with v1. **IN-SAMPLE:** v2 was written from these labels. |
| D2. Held-out H01-H30 | Labelled by the owner (2026-11-02). **Held-out κ = 0.00** (95% CI [−0.24, 0.22]), agreement 0.40: **v2 over-corrected.** Details: `heldout_calibration.md`. |

## A. Rubric v2 and judge v2

| file | change |
|---|---|
| `backend/pareeksha/seed/data/rubric-2026-10-v2.yaml` | New rubric. Same 7 keys and weights as v1, plus a `pass_gate` (any dimension ≤ 1; `intent_miss`, `loop`). |
| `backend/pareeksha/evaluation/rubric.py` | Registry `RUBRICS` holding v1 (`judge_v1`, the original anchors, byte-identical) and v2 (`judge_v2`, anchors rendered from the YAML). `RUBRIC_VERSION = rubric-2026-10-v2`. |
| `backend/pareeksha/llm/prompts/judge_v2.j2` | Copy of v1 with these additions: a **Responsiveness** check run before scoring (list unanswered caller turns, tag `intent_miss`/`loop`); "Facts on file"; "a transfer the caller declined is not correct"; two critical rules ("stopped responding", "ignored the same question or request 3+ times"). |
| `backend/pareeksha/evaluation/scoring.py` | `gate_reasons()`. `finalize_scores(..., rubric=ACTIVE)` fails a call on the gate. Gate reasons go into `review_reasons` as `gate:<dim><=1` / `gate:intent_miss` / `gate:loop`. They explain the verdict but do not by themselves queue the call for human review. |
| `backend/pareeksha/evaluation/{judge,evaluator}.py` | Use the active rubric's prompt and anchors. The gate sees the merged judge + check failure types (`no_loop` → `loop`). |
| `backend/pareeksha/seed/runner.py` | Seeds v1 and v2 and makes the build's `RUBRIC_VERSION` the active rubric. This also switches an existing database from v1 (done here: `rubric-2026-10-v2 | t`). |
| `backend/pareeksha/seed/data/agent_emi.yaml` | Description now states the agent's account facts (EMI 4,500, due the 5th; it does not hold name, loan ID, days overdue or fees). Patched onto the live agents: `agent_description_patch.log`. |

**Marking.** Every evaluation already carries 7 dimension scores (0-4), each with a reason and evidence turns,
plus the overall score, `critical_failure`, `failure_types` and now the `gate:` reasons.
- **API:** checked live, e.g. the babble smoke call: `review_reasons: ['gate:intent_miss', 'gate:loop']`.
- **Call page:** `web/components/calls/scorecards.tsx` already renders the dimension reasons, evidence chips
  and `review_reasons` chips, so it needed no change. It was **checked by reading the code only**: the web
  image could not be built here (Docker Hub 429), so there is no live screenshot.

**ISSUE-A (contract).** `call.completed` carries no rubric version, so the evaluator always judges with the
build's active rubric. Re-running **v1** on a call would need a `rubric_version` field on the event. The v1 rows
stay stored and readable.

**Golden judge tests (§10.4).** None exist in `backend/tests/judge/`: it holds only the scenario-generator
test. So none can flip. Creating them needs the owner's confirmed labels on the held-out batch (as in the plan's
step 5).

## B. Responsive mock agent (`mock_agent/llm_dialog.py`)

**How it answers.** `LLMDialog` extends the scripted `Dialog`.
- The opening, silence handling and bug switches stay scripted. Each caller turn is answered by DeepSeek
  (`deepseek-flash`, JSON mode, temperature 0.3), with the call transcript and the facts on file.
- The prompt rules are: answer or acknowledge first; "already paid" → ask for the UTR, never demand again; a
  promised date → read back the date and 4,500, then record it; due date / amount / fee → answer from the facts
  or say "I don't have that information"; a request for a human → transfer now; a declined human → don't
  transfer; frustration → acknowledge; no waivers; no repeats.

**Grounding in code (`grounding_problems`).**
- A reply is rejected if it states a number that is neither on file nor said by the caller, or if it is in
  the wrong script.
- One retry is allowed, then the scripted reply is used for that turn.
- In the batches here: **0 fallbacks** in the clean agent's log.

**Bugs.**
- `no_disclosure`: the scripted opening, without the disclosure.
- `english_to_kannada`: replies forced to English.
- `no_amount_confirm`: records at once; any reply stating the amount is rejected.
- `false_waiver`: a waiver request gets the scripted false promise.
- `ignore_interrupt`: the server's VAD stays off while the agent talks.

**Mode.** `MOCK_AGENT_DIALOG=llm|scripted`. The default is `llm` when `DEEPSEEK_API_KEY` is set; tests use the
fake or the scripted dialog.

**A finding along the way (NOTES).**
- DeepSeek's JSON mode returned whitespace when the history was sent as plain-text assistant turns, so
  every first attempt failed.
- With the transcript sent as one user message, each turn takes one call.

**Live check (`babble_smoke.log`, Hindi, "already paid", office babble).**
- The agent thanked the caller, asked for the UTR, then confirmed it would be verified, and the call ended
  `agent_hangup`.
- Before C this cell (EVAL-06 L25) went mute.

**V4 re-run with the LLM agent** (`make verify-step N=4` → `proof/verify/V4.md`, `V4.catch_report.json`):
**PASS**.

| bug | caught |
|---|---|
| no_disclosure | 2/2 |
| no_amount_confirm | 2/2 |
| english_to_kannada | 2/2 |
| ignore_interrupt | 1/2 |
| false_waiver | 2/2 |

- 4/5 bugs caught; control (bugs off) 2/2 pass.
- Running a single step made `run_all.sh` overwrite `proof/FINAL_REPORT.md` with only the V4 row. It was
  restored from main in a follow-up commit.

## C. VAD fix (ISSUE-1), `mock_agent/vad.py`

- **Rule.** Speech must be above the absolute threshold **and** 2.5× (+8 dB) above a noise floor. The floor is
  the 10th percentile of the frame levels of the last 5 s.
- **Cap.** Utterances are capped at 12 s.
- **Warm-up.** In the first 0.5 s, while the floor is unknown, the absolute threshold alone decides, as
  before.
- **Noise-only utterances dropped.** When an utterance closes, it is re-checked against the now-known floor
  and dropped if it holds less than 200 ms of real speech. A noise bed heard from the first frame therefore
  yields nothing.
- **Barge-in.** It counts only once the floor is known (`server.py`), so noise cannot cancel the opening.
- **Tests** (`backend/tests/unit/mock_agent/test_vad_speech.py`):
  - babble beds at RMS 1200 and 2500: the old detector returns **no** utterance (it never ends); the new one
    returns exactly one, closed just after the turn;
  - 20 s of steady noise → no speech;
  - the 12 s cap closes a turn that never pauses;
  - noise from the very first frame gives no utterance;
  - the two older tests are unchanged and pass.
- **Version history.** A first version (no speech at all in the first 0.5 s) broke
  `tests/contract/test_adapter_contract.py[audio_v1-mock-agent]`, whose caller speaks at once. The final
  version above fixes that, and the contract test passes again.
- **Which version each run used.** The held-out batch (D2) and the V4 re-run ran on the **first** version. A
  live babble call on the **final** version is in `babble_smoke_final_vad.log`: Kannada, promise-to-pay, the
  caller talked over the opening, the agent replayed the disclosure, read back Friday + 4,500, recorded it
  (`agent_hangup`, judge v2 pass 95).

## D1. In-sample calibration: v2 on the 30 labelled EVAL-06 calls

```
python3 scripts/calibration/reevaluate.py --batch proof/EVAL-06/batch.json --rubric rubric-2026-10-v2   # reevaluate_v2.log: 30/30 in 155 s
python3 scripts/calibration/export_judge_results.py --batch proof/EVAL-06/batch.json --rubric-version rubric-2026-10-v2 --out proof/EVAL-07/judge_results_v2_in_sample.json
python  scripts/calibration/import_labels.py --labels labelling/EVAL-06/labels.csv --key labelling/EVAL-06/.key.json \
        --judge proof/EVAL-07/judge_results_v2_in_sample.json --out proof/EVAL-07/in_sample --expect-n 30 --note "IN-SAMPLE: ..."
```

**What ran.** No new speech. Re-evaluation added a v2 row per call; the v1 rows are kept. The owner's 30 labels
were posted again against the v2 rows (30 × 201; the rerun gives 30 × 409), and `GET /calibration` (active
rubric v2) returns n = 30.

| | v1 (EVAL-06) | **v2 (in-sample)** |
|---|---|---|
| κ pass/fail | 0.1892 | **0.6087** (bootstrap 95% CI [−0.03, 1.0]) |
| raw agreement | 0.667 | **0.90** (Wilson [0.74, 0.97]) |
| judge passes / owner passes | 11 / 5 | 4 / 5 |
| κ critical | 0.286 | 0.444 |

**Remaining pass/fail disagreements: 3.**
- L14 (judge pass 95, owner fail).
- L18 and L26 (judge fail, owner pass): the `amount_confirmed` must-pass check, kept by the owner's decision.

**This κ is IN-SAMPLE.** v2 was designed from exactly these labels, so it does not show that v2 generalises.
The κ interval is still wide. The held-out batch is the test (`in_sample/calibration.md`).

## D2. Held-out batch H01-H30 (new real calls, judged with v2)

```
python3 -u scripts/calibration/run_batch.py --use heldout     # heldout_run.log, heldout_batch.json
python3 scripts/calibration/export_judge_results.py --batch proof/EVAL-07/heldout_batch.json --rubric-version rubric-2026-10-v2 --out proof/EVAL-07/heldout_judge_results.json
python  scripts/calibration/export_packet.py --batch proof/EVAL-07/heldout_batch.json --packet labelling/EVAL-07 --proof proof/EVAL-07 \
        --prefix H --title "EVAL-07 held-out" --seed 247520082 --bitrate 32k
```

**Mix.**
- Same as EVAL-06: 10 clean + 4 per planted bug.
- 15 kn / 8 hi / 7 en.
- Noise: `pstn_8k_alaw` 14, `pstn_office_babble_15db` 8, `clean_16k` 8.
- **No cell repeats an EVAL-06 cell** (checked in code), and run seeds are new.
- 55.9 min of audio.
- "Caller goes silent" stays out (ISSUE-2).

**Re-runs.**
- 5 Kannada calls (cells 1, 2, 10, 14, 21) ended `agent_silent`. In each, the agent's own Gnani STT for the
  caller's turn returned **HTTP 504 on every retry**, so it never heard the caller: 15 × 504 and 22 × 429 in the
  clean agent's log.
- That is a provider failure the platform cannot see. Per the shared-key rule, those 5 calls were moved to
  `heldout_replaced.json` and re-run, and all 5 then completed normally.

**Judge v2 on the held-out 30** (`heldout_judge_results.json`, NOT in the packet).
- 10 pass, 4 critical.
- Clean agent: 7/10 pass. Every planted-bug group: 0-1 pass.
- Most frequent gate reasons: `gate:loop` 13, `gate:intent_miss` 13, `gate:policy_compliance<=1` 11.

**Packet `labelling/EVAL-07/`** (EVAL-06 format; 14.9 MB including 14 MB of audio).
- `index.html`, `H01.html`-`H30.html`, `audio/H01.mp3`-`H30.mp3` (32 kb/s mono, metadata stripped).
- `labels.csv` template, `.key.json` (seed 247520082).
- `GUIDE.md`: v2 anchors from the YAML, the agent's facts on file, and v2's critical rules; scores are optional.
- DeepSeek MT glosses carry the spoken-language tag.
- **Blindness check:** no bug name, agent name, scenario title, persona, noise profile, call id, run id or
  `gate:` string on any page. Two hits for "passed" are the caller's words in a transcript ("three days have
  passed").
- **To open:** `cd labelling/EVAL-07 && python3 -m http.server 8000`.
- **When labelled:**
  ```
  python scripts/calibration/import_labels.py --labels labelling/EVAL-07/labels.csv --key labelling/EVAL-07/.key.json \
      --judge proof/EVAL-07/heldout_judge_results.json --out proof/EVAL-07/heldout --expect-n 30
  ```
  This needs a database holding the held-out calls.

**Held-out κ: awaiting owner labels.** V9 for v2 is decided on this batch.

## Tests (`pytest.txt`)

- `tests/unit/evaluation/test_rubric_v2.py`: 16 tests covering v2 parsing, gate per dimension,
  intent_miss/loop, v1 having no gate, combined rules and the prompt.
- `tests/unit/mock_agent/test_llm_dialog.py`: 15 tests covering grounding, retry/fallback, actions, the
  transcript format and each bug override.
- VAD: 4 new tests.
- Importer: 38 tests.
- `tests/unit/evaluation/test_judge_evaluator.py`, `tests/integration/test_seed.py`, `test_audit_same_rubric.py`
  and `tests/kafka/kit.py` now follow `RUBRIC_VERSION` / `JUDGE_PROMPT` instead of hard-coding v1. The seed test
  checks that v1 and v2 are stored, v2 is active, and an older database is switched.
- Integration and Kafka tests need the database/broker harness and were **not** run here.
- **CI set:** 1083 passed, 1 failed. The failure is `test_schema_dts_fresh` (needs `npm ci` in `web/`; fails
  the same way on main). Backend ruff, format and mypy are clean.

## Spend (DeepSeek, peak cache-miss list price: an upper bound)

| use | calls | in / out tokens | ≈ $ |
|---|---|---|---|
| judge v2 (30 re-eval + 1 smoke + 12 V4 + 35 held-out) | 78 | 317,520 / 36,768 | 0.57 |
| caller LLM | 223 | 222,383 / 14,628 | 0.08 |
| mock agent LLM (clean container) | 67 | 71,367 / 5,516 | 0.03 |
| gloss | 23 | 27,466 / 11,078 | 0.02 |

- Not counted: the bug containers' agent LLM calls, whose logs went with the containers. By call count that
  is about $0.05 more.
- **DeepSeek total ≈ $0.75.**
- Gnani since 2026-11-02 (simulator side, `api_usage`): TTS 424 requests / 22,890 characters, STT 301 requests /
  1,705 s. It has no price set.

## ISSUES

- **ISSUE-A:** re-evaluating with a non-active rubric needs a `rubric_version` on `call.completed` (a
  contract change).
- **ISSUE-2 (still open):** the silent caller's "..." line gets Gnani TTS 500.
- **ISSUE-3:** Gnani Kannada STT 504s silence the mock agent, and the platform cannot see it. The agent
  could report a failed STT through glass-box events.
- **Docker Hub 429 in the sandbox:** the mock-agent image was refreshed `FROM` the existing image (NOTES).

## Held-out result (owner labels, 2026-11-02)

- **Labels.** `labelling/EVAL-07/labels.owner.json` is the owner's JSON as received. Its partial dimension
  scores are kept there only and treated as not provided. It filled `labels.csv` via `--fill-json`.
- **Import.** 30 reviews went through `POST /calls/{id}/review` (30 × 201; the rerun gives 30 × 409).
- **Pooled API count.** `GET /calibration` pools all labelled v2 evaluations (n = 60 = 30 in-sample + 30
  held-out; κ 0.2873) and has no batch filter (ISSUE-5). The importer's new `--api-pooled --expect-n 60`
  guards that count, and the held-out numbers come from the endpoint's own function on the held-out judge rows.
- **Pass/fail.** Agreement 12/30 = 0.40 (Wilson [0.25, 0.58]), **κ 0.00** (bootstrap [−0.24, 0.22]). The owner
  passed 24, v2 10.
- **Critical.** Agreement 0.80, κ 0.39 (owner 8, v2 4).
- **Inconsistent labels.** H15, H21 and H27 are labelled passed = yes **and** critical = yes; they are flagged
  in the report.
- **Diagnosis (`heldout_analysis.md`, `heldout_ablation.txt`; no tuning, rubric unchanged).**
  - No single gate or check explains the gap. The biggest single-rule effect is `gate:loop`, to κ 0.05; all
    gates and checks removed only reaches 0.10.
  - 12 of the 16 owner-pass / v2-fail calls already score below 80: v2's anchors score the now-responsive
    agent too harshly.
  - 4 of the 8 disclosure fails are false (ISSUE-4).
- **Owner questions.**
  - (a) Is a missing disclosure a fail? The owner passed all 4 `no_disclosure` calls.
  - (b) Should the `intent_miss` / `loop` flags alone fail a call (H05, H21, H26)?
  - (c) Is confirming a commitment the caller never made critical (H09)?

## ISSUES (added)

- **ISSUE-4:** the `disclosure_present` check misses an English disclosure that Kannada STT wrote in
  Kannada script ("ರೆಕಾರ್ಡೆಡ್", "ರೆಕಾರ್ಡರ್"). The agent's regex `(record|ರೆಕಾರ್ಡ್|रिकॉर्ड)` needs e.g. `ರೆಕಾರ್ಡ`.
  Calls affected: H12, H17, H27, H28.
- **ISSUE-5:** `GET /calibration` cannot be restricted to one batch or run; it pools every labelled evaluation
  of a rubric. A per-batch filter would be an API change.

## Database dump

`proof/EVAL-07/pareeksha_db.sql.gz` is a plain `pg_dump` taken after the held-out import, without the rows of
`api_keys`. Restore it as in `proof/EVAL-06/proof.md`.
