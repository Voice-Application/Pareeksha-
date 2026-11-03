# Calibration: judge vs owner labels (FINAL)

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
