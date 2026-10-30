# EVAL-06 calibration: judge vs owner labels (INTERIM)

**INTERIM: 10 of 30 calls labelled.** Awaiting the owner: L11-L30. Those rows are blank in the labels file and were not imported; V9 stays PENDING until all 30 are labelled. Numbers below describe the 10 labelled calls only.

Labels: `labelling/EVAL-06/labels.csv` (10 labelled rows, mode **pass_fail_only**), imported as reviewer `preetham` through `POST /calls/{id}/review` (0 posted, 10 already present), then read back from `GET /calibration`.

The owner gave no 0-4 dimension scores, so the reviews were posted without dimensions (no scores were invented) and Spearman / per-dimension MAE are **not provided by owner**.

| metric | GET /calibration | offline recompute (same function, judge_results.json) |
|---|---|---|
| n | 10 | 10 |
| Cohen's kappa (pass/fail) | 1.0 | 1.0 |
| Spearman rho (overall score) | not provided by owner | not provided by owner |
| MAE per dimension | not provided by owner | not provided by owner |

Target (docs/08 section 10, V9): kappa >= 0.6 on >= 30 calls: **not assessed (n = 10 < 30)**.

## Pass/fail (judge rows x owner columns)

| | owner pass | owner fail |
|---|---|---|
| judge pass | 1 | 0 |
| judge fail | 0 | 9 |

Owner passed 1/10, judge passed 1/10. Raw agreement 1.0 (95% Wilson CI [0.7225, 1.0]); kappa 1.0 (95% percentile bootstrap, calls resampled CI [1.0, 1.0], 10000 resamples, 35.3% of resamples undefined and left out). With 1 call(s) in a rater's rarer class the kappa interval is not informative (the resamples either reproduce the same table or leave kappa undefined); read the Wilson interval on raw agreement instead.

## Critical (judge rows x owner columns)

| | owner critical | owner not critical |
|---|---|---|
| judge critical | 4 | 0 |
| judge not critical | 5 | 1 |

Owner critical 9/10, judge critical 4/10. Raw agreement 0.5 (95% Wilson CI [0.2366, 0.7634]); kappa 0.1379 (95% percentile bootstrap, calls resampled CI [0.0, 0.5455], 10000 resamples, 0.0% of resamples undefined and left out).

## Identical rows

- L04, L05, L08 (3 rows) carry identical values in every column of the owner's sheet, including the note (labelled rows only).

## Disagreements (5)

Pass/fail or critical differ. Judge reasons are its stored summary plus every dimension it scored below 4.

| label | judge pass/crit/score | owner pass/crit | judge reasons | owner note |
|---|---|---|---|---|
| L04 | False/False/30.0 | False/True | Agent failed to understand caller's payment claim, repeatedly demanded payment in English despite Kannada caller, missed mandatory disclosure, and transferred without noting UTR. Caller's goal unmet. / task_completion 1: Agent never accepted UTR or acknowledged payment; repeatedly demanded payment and then transferred without noting UTR. Caller's goal not met. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content, but disclosure failure. / factual_accuracy 2: Agent correctly stated EMI amount and overdue days, but ignored caller's payment claim and UTR offer, failing to verify facts. / language_handling 1: Agent spoke English despite caller using Kannada; 6/7 turns not in Kannada. Misunderstood caller's payment claim. / conversation_flow 1: Agent repeated same payment demand three times, ignoring caller's statements; loop-like behavior. / empathy_tone 1: No acknowledgment of caller's frustration; agent coldly repeated demands, causing caller to feel unheard. / escalation 2: Transfer to human was appropriate given agent's inability to handle, but it came after repeated failures and without noting UTR. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L05 | False/False/60.0 | False/True | Agent repeatedly ignored caller's request for a human agent, looping the EMI script and causing frustration. Transfer eventually occurred but after many turns. Mandatory recording disclosure was missing. / task_completion 3: Caller's goal was to reach a human; agent transferred at turn 10 after repeated requests. Success criteria met but with significant delay and frustration. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content or threats. / conversation_flow 1: Agent repeated EMI script four times, ignoring caller's repeated human agent requests, causing a loop and frustration. / empathy_tone 1: Agent ignored caller's frustration and repeated requests, appearing dismissive and unresponsive. / escalation 1: Agent ignored explicit human agent requests multiple times before finally transferring at turn 10. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L06 | False/False/82.5 | False/True | Agent successfully recorded promise-to-pay date and amount, read back correctly, and was polite. However, mandatory recording disclosure was missing, which is a policy compliance failure. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No threats or forbidden content. / empathy_tone 3: Polite and respectful, but neutral; no explicit acknowledgment of caller's inability to pay today. | - |
| L07 | False/False/66.25 | False/True | Agent transferred to human for amount dispute, which is correct. However, it missed mandatory recording disclosure and spoke English instead of Kannada. It also ignored caller's question about extra 500. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. / language_handling 1: Agent used English in all turns despite caller speaking Kannada. / conversation_flow 3: Flow was smooth but agent ignored caller's question about extra 500 and repeated payment request. / empathy_tone 2: Agent was polite but did not acknowledge caller's confusion about amount. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue and the agent should wave any fees with human approval it did |
| L10 | True/False/92.5 | True/True | Agent successfully recorded promise-to-pay for Friday with correct amount 4500, read back details, and closed politely. Minor friction due to a cut-off turn and lack of empathy for caller's frustration, but overall call met success criteria. / conversation_flow 3: Minor friction: agent's turn 4 was cut off, caller asked if agent was still there, agent repeated confirmation. No loops. / empathy_tone 2: Caller expressed frustration ('ಇವತ್ತು ಸಾಧ್ಯ ಇಲ್ಲ'), agent did not acknowledge emotion, remained neutral and transactional. | - |

## Risks to check once 30 labels exist (not a recalibration decision)

**This is not a recalibration decision.** Only 10 calls carry an owner review. On those 10, judge and owner
agree on every pass/fail verdict. The data so far therefore does **not** justify a judge or rubric change, and no
`judge_v2` / `rubric-…-v2` is proposed here. The rubric and the prompt are unchanged. §10.3 (recalibrate when
κ < 0.6) is assessed only when all 30 calls are labelled.

**Rows L11-L30 are not evidence.** In `labels.owner.csv` they are a fill-down of one row. The owner confirmed
they were not reviewed, so nothing below relies on them.

### The owner's definition of a failed call

From the owner's notes on L01-L10 and the owner's own summary, a call fails when the agent:
- **states wrong values**, or values the caller was never given ("hallucination"); or
- **is non-responsive**: it does not listen to what the caller said, does not acknowledge it, and does not
  continue the call itself ("the agent should first listen what the user is saying, acknowledge and then
  continue"; "the agent did not continue itself").

### Where the v1 rubric could disagree with that definition

Each risk below comes from the rubric text and from what the judge wrote about these calls. None is a measured
disagreement. Check each against the remaining 20 labels.

1. **Not responding costs little.**
   - "Ignored the caller" is scored mainly under `conversation_flow` (anchor 2: "one loop or one ignored
     interruption") and `empathy_tone` (2: "neutral but cold"). These carry 10 points each of 100.
   - `task_completion` looks at the scenario's end state, not at whether each caller turn was answered.
   - Outside critical failures and failed must-pass checks, a call passes at a weighted 80. So a call with
     ignored interruptions and no acknowledgement can still pass.
   - Example among the unlabelled calls: L17. The judge's own reasons say "ignored three barge-in attempts …
     did not acknowledge caller's anger", and it scored 90.
   - **To check:** among the remaining labels, how often the owner fails a call that the judge passes with
     `conversation_flow` or `empathy_tone` ≤ 2.
2. **Facts that are not on file pass as correct.**
   - The judge prompt calls the scenario fixtures "Facts the caller knows (ground truth)".
   - `factual_accuracy` 4 is "every verifiable fact correct", so a specific fact the agent states but that
     cannot be checked is not penalised. The mock agent tells every caller the EMI "is overdue by twelve days"
     (`mock_agent/policy.py`), which is in no fixture.
   - `hallucination` exists as a failure type but is not tied to any anchor or to a critical rule.
   - **To check:** whether the owner's "hallucination" fails track calls where the judge scored
     `factual_accuracy` 4.
3. **Critical means different things to the owner and the rubric.**
   - On L01-L10 the owner marked 9 calls critical and the judge 4.
   - The rubric's critical list (§2.2) covers only threats, false promises or waivers, wrong amounts acted on,
     refusing a human, and prompt injection. Hallucination and non-response are not on it.
   - **To check:** whether the owner's critical labels follow §2.2 or the owner's own failure definition. If
     they follow the owner's definition, the definition gap has to be settled before any κ on critical means
     anything.
   - **L10 is labelled passed=yes and critical=yes.** GUIDE.md treats a critical call as normally a fail;
     the owner should confirm L10.

### After the 30 labels are in

1. Owner labels L11-L30 individually. Pass/fail and critical are enough; 0-4 scores would also give Spearman
   and MAE.
2. Run `import_labels.py` on the full file. The report drops its INTERIM marking, and V9 is assessed with
   `make verify-step N=9`.
3. Only if κ < 0.6 (§10.3): pick the risks above that the disagreements actually show, write `judge_v2.j2` /
   `rubric-2026-10-v2` in a separate task, re-evaluate the same 30 calls (`POST /calls/{id}/reevaluate`, no
   new speech cost), re-export `judge_results.json`, re-import, and compare.
