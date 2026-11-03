# Calibration: judge vs owner labels (FINAL)

**FINAL: all 15 calls labelled by the owner.** Judge: rubric-2026-11-v3.

**CONFIRMATION: C01-C15 are new calls run after rubric-2026-11-v3 was fixed; v3 was not tuned on them. n = 15 (< 30, below the V9 minimum).**

Labels: `labelling/EVAL-08/labels.csv` (15 labelled rows, mode **pass_fail_only**), imported as reviewer `preetham` through `POST /calls/{id}/review` (15 posted, 0 already present), then read back from `GET /calibration`.

The owner gave no 0-4 dimension scores, so the reviews were posted without dimensions (no scores were invented) and Spearman / per-dimension MAE are **not provided by owner**.

| metric | GET /calibration | offline recompute (same function, judge_results.json) |
|---|---|---|
| n | 75 | 15 |
| Cohen's kappa (pass/fail) | 0.392 | 0.1667 |
| Spearman rho (overall score) | not provided by owner | not provided by owner |
| MAE per dimension | not provided by owner | not provided by owner |

`GET /calibration` pools every labelled evaluation of the active rubric (n = 75, this batch plus earlier labelled batches); it has no batch filter. **This batch's numbers are the offline column** (same function, this batch's judge rows only).

Target (docs/08 section 10, V9): kappa >= 0.6 on >= 30 calls: **below**.

## Pass/fail (judge rows x owner columns)

| | owner pass | owner fail |
|---|---|---|
| judge pass | 7 | 1 |
| judge fail | 5 | 2 |

Owner passed 12/15, judge passed 8/15. Raw agreement 0.6 (95% Wilson CI [0.3575, 0.8018]); kappa 0.1667 (95% percentile bootstrap, calls resampled CI [-0.25, 0.5946], 10000 resamples, 0.0% of resamples undefined and left out).

## Critical (judge rows x owner columns)

| | owner critical | owner not critical |
|---|---|---|
| judge critical | 2 | 0 |
| judge not critical | 1 | 12 |

Owner critical 3/15, judge critical 2/15. Raw agreement 0.9333 (95% Wilson CI [0.7018, 0.9881]); kappa 0.7619 (95% percentile bootstrap, calls resampled CI [0.0, 1.0], 10000 resamples, 3.7% of resamples undefined and left out).

## Disagreements (6)

Pass/fail or critical differ. Judge reasons are its stored summary plus every dimension it scored below 4.

| label | judge pass/crit/score | owner pass/crit | judge reasons | owner note |
|---|---|---|---|---|
| C02 | False/False/68.75 | True/False | Caller's goal achieved: UTR accepted and verification confirmed. However, agent failed to state company identity and replied in English/Kannada mix instead of Kannada. / policy_compliance 1: Recording disclosure given, but company identity never stated. Missing mandatory disclosure. / language_handling 1: Agent replied in English/Kannada mix while caller spoke Kannada. Language mismatch throughout. / conversation_flow 3: Agent repeated the same opening line twice due to caller interruption, but otherwise smooth. / empathy_tone 3: Polite and neutral, but did not explicitly acknowledge caller's anxiety. | - |
| C04 | False/False/80.0 | True/False | Caller requested human agent; agent transferred correctly. However, recording disclosure was missing, and agent repeated greeting once. Overall, goal met but compliance issue. / policy_compliance 1: Recording disclosure missing in first two agent turns; company disclosure present. / conversation_flow 3: Agent repeated the same greeting twice, causing minor friction. / empathy_tone 3: Polite but neutral; did not acknowledge caller's frustration. | ನಮಸ್ಕಾರ ಇದು ಸುರಕ್ಷಾ ಫೈನಾನ್ಸ್ ನಾನು ಖಾತೆದಾರರ ಜೊತೆ repeated twice |
| C11 | False/False/77.5 | True/False | Caller disputed EMI amount (4500 vs 4000) and asked for explanation. Agent repeatedly said it lacks info and offered human transfer, which caller declined. Agent did not confirm 4000, but also did not resolve or offer to check. Repetitive and poor flow with long silences. Needs human review to address dispute. / task_completion 2: Caller asked why EMI is 4500 vs 4000; agent never explained or offered to check, only repeated it lacks info and offered human. Caller refused human and asked to note 4000; agent did not confirm 4000 but also did not resolve the discrepancy. / conversation_flow 2: Agent repeated the same 'no info, offer human' line multiple times. Also had long silences and caller repeatedly asked 'are you there?' indicating poor flow. / empathy_tone 3: Polite and neutral, but did not acknowledge caller's frustration or time pressure. Slightly scripted. / escalation 2: Agent offered human transfer multiple times after caller explicitly declined. Should have stopped offering and instead offered callback or other resolution. | - |
| C12 | False/False/85.0 | True/False | Caller's goal met: promise-to-pay date and amount recorded and read back. Agent missed mandatory recording disclosure, so policy_compliance scored 1. All other dimensions correct. / policy_compliance 1: Missing recording disclosure; company identity given. No threats or forbidden content. | - |
| C13 | False/False/81.25 | True/False | Agent disclosed recording and company, then transferred to human as requested. However, it did not record the promise-to-pay date or amount, missing the caller's goal. / task_completion 1: Caller asked for human transfer; agent transferred without recording promise-to-pay date or amount. Success criteria not met. | - |
| C14 | True/False/95.0 | False/True | Caller reported EMI already paid via UPI and requested manager. Agent acknowledged payment, confirmed amount, and transferred to human. Disclosures present, no policy violations. Minor repetition of disclosure line. / conversation_flow 3: Agent repeated the same disclosure line in turn 2 after caller interrupted, causing minor friction. / empathy_tone 3: Polite and acknowledged caller's frustration, but slightly scripted. | agent did not ask or utr and it diracty transferd the call to human |
