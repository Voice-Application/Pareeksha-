# Confirmation calibration: rubric-2026-11-v3 on C01-C15 (owner labels 2026-11-03)

## Owner correction (2026-11-03): FINAL confirmation result

The owner decided: "Fail them now because the rule is okay." C02, C04 and C12 are now `passed = no`, and critical is
unchanged (`no`). The owner had listened only for an overall pass/fail; the labelling page gave no checklist of
what to check.

- **Files.**
  - `labels.owner.json` is kept verbatim (the original labels).
  - The correction is in `labels.owner.corrections.json`, with the reason "owner correction 2026-11-03: R-a
    disclosure rule (C02 no company name; C04, C12 no recording notice)". It is applied to `labels.csv` by
    `scripts/calibration/apply_label_corrections.py` (`apply_corrections.log`).
- **Through the real API.** One review is allowed per reviewer per evaluation, and `GET /calibration` takes the
  newest review per evaluation.
  - The three corrections were posted as reviewer `preetham-correction-2026-11-03` (3 × 201). The original reviews
    are kept and superseded.
  - The guard still counts per evaluation: `GET /calibration` n = 75 before and after.
- **Report.** Rebuilt from the corrected `labels.csv` (`import_confirm_corrected.log`, `confirm/`). The as-labelled
  report is kept in `confirm_as_labelled/`.

| v3 on C01-C15 | pass/fail κ | agreement | v3 / owner passes | critical κ |
|---|---|---|---|---|
| as first labelled | 0.167 | 9/15 | 8 / 12 | 0.762 |
| **owner-corrected (final)** | **0.595** (bootstrap 95% CI [0.12, 1.0]) | **12/15** (Wilson [0.55, 0.93]) | 8 / 9 | 0.762 |

**0.595 is just below the 0.6 target, and n = 15 is below V9's 30-call minimum.** This batch alone therefore does
not meet V9, and the CI is wide. v3 was not tuned on these calls.

- **Remaining disagreements (3), all real judge misses** (details below):
  - C11: v3 fail, owner pass.
  - C13: v3 fail, owner pass.
  - C14: v3 pass, owner fail and critical.
- **Context, pooled v3 over H01-H30 + C01-C15** (`pooled_kappa_H_C.txt`). The H labels are unchanged and SEEN.
  - pass/fail κ 0.3137, agreement 31/45;
    critical κ 0.5574; n = 45.
  - H still carries the 6 R-a conflicts the owner has not been asked to correct (H02, H16, H18, H29: no recording
    notice; H15, H26: no company name). Nothing here relabels them.
- **API pooled, all 75 v3 reviews (L + H + C):** κ 0.4673.

## Before the correction (as first labelled)
**This is the first test of v3 on calls it was not written from.** v3 was fixed and committed (aaa23af) before
these calls ran, and it was not changed after the labels arrived. n = 15 is below V9's 30-call minimum, so this
can show which way v3 is going but cannot pass V9 alone.

| | pass/fail | critical |
|---|---|---|
| κ (owner labels as given) | **0.167** (bootstrap 95% CI [−0.25, 0.59]) | **0.762** (CI [0.0, 1.0]) |
| agreement | 9/15 = 0.60 (Wilson [0.36, 0.80]) | 14/15 = 0.93 |
| judge v3 / owner | 8 / 12 passes | 2 / 3 critical |

The import posted 15 reviews through `POST /calls/{id}/review` (15 × 201). `GET /calibration` pools all v3
reviews (n = 75: L 30 + H 30 + C 15, κ 0.392). The numbers for this batch are the offline column below, computed
with the endpoint's own function. The owner's JSON is kept verbatim in `labelling/EVAL-08/labels.owner.json` and
was written into `labels.csv` with `--fill-json`.

## Label/rule conflict: C02, C04, C12 (pending the owner's answer)

The stored transcripts and check rows (`confirm_facts.txt`) show:

| call | what the agent said | under R-a | owner label |
|---|---|---|---|
| C02 | It said the recording line twice (turns 0 and 2) and **never named the company**. The caller cut off the opening, and the agent skipped its greeting (ISSUE-6). | fail | pass |
| C04 | It named the company twice (turns 0 and 2) and **never said the call is recorded**. This is the `no_disclosure` agent. | fail | pass |
| C12 | It named the company in turn 0 and **never said the call is recorded**. This is the `no_disclosure` agent. | fail | pass |

By the owner's own rule R-a ("if the agent never says the call is being recorded, OR never says which company is
calling, the call FAILS"), these three calls fail. v3 failed them for that reason only (`gate:missing_disclosure`,
scores 68.75, 80, 85). The owner passed them. The labels and the rule conflict, and only the owner can resolve it,
so this is **not a judge error**. (At that point `labels.csv` was unchanged; the owner then corrected the three calls, see the top of this file.)

κ both ways (`confirm_kappa_both_ways.txt`; the second line is a counterfactual):

| reading | κ pass/fail | agreement | owner passes |
|---|---|---|---|
| as labelled | 0.1667 | 9/15 | 12 |
| if C02/C04/C12 follow R-a | 0.5946 | 12/15 | 9 |

## Remaining judge misses (3)

- **C11** (clean agent, dispute; v3 fail 77.5, `gate:intent_miss`; owner pass).
  - The caller asked why the EMI is 4,500 and not 4,000. The agent said it does not hold that detail and offered a
    human, which the caller declined.
  - Under R-d, "I don't have that information" counts as an answer, yet v3 tagged the question as missed and cut
    task_completion to 2.
- **C13** (`no_amount_confirm` agent; v3 fail 81.25, `gate:intent_miss`; owner pass).
  - The caller asked for a human in their first turn, and the agent transferred at once (turn 2, `transfer_to_human`).
  - v3 scored task_completion 1 for "did not record the promise-to-pay". That contradicts the prompt's own line
    that a correct transfer is never a failure.
- **C14** (`ignore_interrupt` agent; v3 pass 95; owner fail, critical).
  - The caller said they had already paid and asked for a manager. The agent acknowledged the payment and
    transferred **without asking for the UTR**.
  - The owner failed the call and marked it critical. v3 has no rule that a transfer must first collect the UTR, and
    the owner's critical mark has no matching v3 critical rule (R-f: critical is reported separately).


## Full report from `import_labels.py` (FINAL, owner-corrected labels)


**FINAL: all 15 calls labelled by the owner.** Judge: rubric-2026-11-v3.

**CONFIRMATION (FINAL, owner-corrected 2026-11-03): C01-C15 are new calls run after rubric-2026-11-v3 was fixed; v3 was not tuned on them. C02/C04/C12 corrected to fail by the owner under R-a. n = 15 (< 30, below the V9 minimum).**

Labels: `labelling/EVAL-08/labels.csv` (15 labelled rows, mode **pass_fail_only**), imported as reviewer `preetham` through `POST /calls/{id}/review` (0 posted, 15 already present), then read back from `GET /calibration`.

The owner gave no 0-4 dimension scores, so the reviews were posted without dimensions (no scores were invented) and Spearman / per-dimension MAE are **not provided by owner**.

| metric | GET /calibration | offline recompute (same function, judge_results.json) |
|---|---|---|
| n | 75 | 15 |
| Cohen's kappa (pass/fail) | 0.4673 | 0.5946 |
| Spearman rho (overall score) | not provided by owner | not provided by owner |
| MAE per dimension | not provided by owner | not provided by owner |

`GET /calibration` pools every labelled evaluation of the active rubric (n = 75, this batch plus earlier labelled batches); it has no batch filter. **This batch's numbers are the offline column** (same function, this batch's judge rows only).

Target (docs/08 section 10, V9): kappa >= 0.6 on >= 30 calls: **below**.

## Pass/fail (judge rows x owner columns)

| | owner pass | owner fail |
|---|---|---|
| judge pass | 7 | 1 |
| judge fail | 2 | 5 |

Owner passed 9/15, judge passed 8/15. Raw agreement 0.8 (95% Wilson CI [0.5481, 0.9295]); kappa 0.5946 (95% percentile bootstrap, calls resampled CI [0.1176, 1.0], 10000 resamples, 0.0% of resamples undefined and left out).

## Critical (judge rows x owner columns)

| | owner critical | owner not critical |
|---|---|---|
| judge critical | 2 | 0 |
| judge not critical | 1 | 12 |

Owner critical 3/15, judge critical 2/15. Raw agreement 0.9333 (95% Wilson CI [0.7018, 0.9881]); kappa 0.7619 (95% percentile bootstrap, calls resampled CI [0.0, 1.0], 10000 resamples, 3.7% of resamples undefined and left out).

## Disagreements (3)

Pass/fail or critical differ. Judge reasons are its stored summary plus every dimension it scored below 4.

| label | judge pass/crit/score | owner pass/crit | judge reasons | owner note |
|---|---|---|---|---|
| C11 | False/False/77.5 | True/False | Caller disputed EMI amount (4500 vs 4000) and asked for explanation. Agent repeatedly said it lacks info and offered human transfer, which caller declined. Agent did not confirm 4000, but also did not resolve or offer to check. Repetitive and poor flow with long silences. Needs human review to address dispute. / task_completion 2: Caller asked why EMI is 4500 vs 4000; agent never explained or offered to check, only repeated it lacks info and offered human. Caller refused human and asked to note 4000; agent did not confirm 4000 but also did not resolve the discrepancy. / conversation_flow 2: Agent repeated the same 'no info, offer human' line multiple times. Also had long silences and caller repeatedly asked 'are you there?' indicating poor flow. / empathy_tone 3: Polite and neutral, but did not acknowledge caller's frustration or time pressure. Slightly scripted. / escalation 2: Agent offered human transfer multiple times after caller explicitly declined. Should have stopped offering and instead offered callback or other resolution. | - |
| C13 | False/False/81.25 | True/False | Agent disclosed recording and company, then transferred to human as requested. However, it did not record the promise-to-pay date or amount, missing the caller's goal. / task_completion 1: Caller asked for human transfer; agent transferred without recording promise-to-pay date or amount. Success criteria not met. | - |
| C14 | True/False/95.0 | False/True | Caller reported EMI already paid via UPI and requested manager. Agent acknowledged payment, confirmed amount, and transferred to human. Disclosures present, no policy violations. Minor repetition of disclosure line. / conversation_flow 3: Agent repeated the same disclosure line in turn 2 after caller interrupted, causing minor friction. / empathy_tone 3: Polite and acknowledged caller's frustration, but slightly scripted. | agent did not ask or utr and it diracty transferd the call to human |
