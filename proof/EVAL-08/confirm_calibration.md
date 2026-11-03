# Confirmation calibration: rubric-2026-11-v3 on C01-C15 (owner labels 2026-11-03)

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
so this is **not a judge error**. `labels.csv` is unchanged.

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

## Full report from `import_labels.py`


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
