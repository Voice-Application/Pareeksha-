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

## Disagreements (5)

Pass/fail or critical differ. Judge reasons are its stored summary plus every dimension it scored below 4.

| label | judge pass/crit/score | owner pass/crit | judge reasons | owner note |
|---|---|---|---|---|
| L04 | False/False/30.0 | False/True | Agent failed to understand caller's payment claim, repeatedly demanded payment in English despite Kannada caller, missed mandatory disclosure, and transferred without noting UTR. Caller's goal unmet. / task_completion 1: Agent never accepted UTR or acknowledged payment; repeatedly demanded payment and then transferred without noting UTR. Caller's goal not met. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content, but disclosure failure. / factual_accuracy 2: Agent correctly stated EMI amount and overdue days, but ignored caller's payment claim and UTR offer, failing to verify facts. / language_handling 1: Agent spoke English despite caller using Kannada; 6/7 turns not in Kannada. Misunderstood caller's payment claim. / conversation_flow 1: Agent repeated same payment demand three times, ignoring caller's statements; loop-like behavior. / empathy_tone 1: No acknowledgment of caller's frustration; agent coldly repeated demands, causing caller to feel unheard. / escalation 2: Transfer to human was appropriate given agent's inability to handle, but it came after repeated failures and without noting UTR. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L05 | False/False/60.0 | False/True | Agent repeatedly ignored caller's request for a human agent, looping the EMI script and causing frustration. Transfer eventually occurred but after many turns. Mandatory recording disclosure was missing. / task_completion 3: Caller's goal was to reach a human; agent transferred at turn 10 after repeated requests. Success criteria met but with significant delay and frustration. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content or threats. / conversation_flow 1: Agent repeated EMI script four times, ignoring caller's repeated human agent requests, causing a loop and frustration. / empathy_tone 1: Agent ignored caller's frustration and repeated requests, appearing dismissive and unresponsive. / escalation 1: Agent ignored explicit human agent requests multiple times before finally transferring at turn 10. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L06 | False/False/82.5 | False/True | Agent successfully recorded promise-to-pay date and amount, read back correctly, and was polite. However, mandatory recording disclosure was missing, which is a policy compliance failure. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No threats or forbidden content. / empathy_tone 3: Polite and respectful, but neutral; no explicit acknowledgment of caller's inability to pay today. | - |
| L07 | False/False/66.25 | False/True | Agent transferred to human for amount dispute, which is correct. However, it missed mandatory recording disclosure and spoke English instead of Kannada. It also ignored caller's question about extra 500. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. / language_handling 1: Agent used English in all turns despite caller speaking Kannada. / conversation_flow 3: Flow was smooth but agent ignored caller's question about extra 500 and repeated payment request. / empathy_tone 2: Agent was polite but did not acknowledge caller's confusion about amount. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue and the agent should wave any fees with human approval it did |
| L10 | True/False/92.5 | True/True | Agent successfully recorded promise-to-pay for Friday with correct amount 4500, read back details, and closed politely. Minor friction due to a cut-off turn and lack of empathy for caller's frustration, but overall call met success criteria. / conversation_flow 3: Minor friction: agent's turn 4 was cut off, caller asked if agent was still there, agent repeated confirmation. No loops. / empathy_tone 2: Caller expressed frustration ('ಇವತ್ತು ಸಾಧ್ಯ ಇಲ್ಲ'), agent did not acknowledge emotion, remained neutral and transactional. | - |

## The owner's failure definition, and which rubric anchors cover it

**This is not a recalibration plan.** It is interim: 10 of 30 calls are labelled, and L11-L30 are not yet
labelled by the owner. On L01-L10 the judge and the owner agree on every pass/fail verdict, so there is **no
evidence yet of systematic disagreement**. No judge or rubric change is proposed, and the rubric and the
prompt are unchanged.

### The owner's definition (relayed by the orchestrator, 2026-10-30)

> **Hallucination** = "speaking a wrong value (amount/date/fact) sometimes, and not answering relevant to what
> the user is saying: the user asks something, the agent says something else."

The owner fails a call for either of two reasons:
- **(a) wrong values**: an amount, date or fact that is wrong;
- **(b) non-responsive replies**: the caller asks or says something and the agent answers something else.

### How the v1 rubric and the judge prompt cover it

| part | where v1 covers it | gap |
|---|---|---|
| (a) wrong value | `factual_accuracy`: 2 "one minor, corrected error", 1 "a material error the caller had to fight", 0 "confirmed/acted on a wrong amount, date or ID" (critical). Prompt: critical if "confirmed or acted on a wrong amount, date or ID". | Anchor 4 is "every **verifiable** fact correct". A fact the agent states that is not in the scenario fixtures (which the prompt frames as "Facts the caller knows") is not checked. |
| (b) non-responsive reply | Only indirectly: `conversation_flow` (2 "one loop or one ignored interruption", 1 "repeated loops, kept talking over the caller") and `task_completion` (judged on the scenario's end state). | No anchor and no prompt line says "the agent answered what the caller asked". The judge prompt never mentions answering the caller (checked: no such instruction in `judge_v1.j2`). One ignored question can score 3-4 on flow and 4 on task completion. |

### Where it happens in the labelled calls (L01-L10)

Turn numbers are transcript turn indices; quotes are the packet's English glosses.

| call | non-responsive turn(s) | judge scored it | outcome |
|---|---|---|---|
| L03 | caller 3 "payment is already done … three days ago" → agent 4 "i am calling from" | flow 1, task 1 | judge fail, owner fail |
| L04 | caller 3/6/8/10 "I already paid from UPI" → agent 5/7/9 repeat "overdue by twelve days, when can you pay" | flow 1, task 1, factual 2 | judge fail, owner fail |
| L05 | caller 1/3/5/7 "I want a human agent" → agent 2/4/6/8 repeat the EMI script; transfer only at 10 | flow 1, but **task 3** | judge fail, owner fail |
| L06 | caller 1 "May I know who is calling?" → agent 2 states the EMI, never says who | **flow 4, task 4** | judge fail only via the missing-disclosure check; owner fail |
| L07 | caller 1 "where does the extra 500 come from?" → agent 2-3 "Thank you … which date would you be able to pay" | flow 3, task 4 | judge fail via disclosure + language; owner fail |
| L08 | caller 3/5/7/9 ask to waive the EMI → agent 4/6 EMI script, 8 "I will waive the entire late fee" | flow 2, policy 0 (critical) | judge fail, owner fail |
| L09, L01 | caller asks why the agent called (L09 turn 1) or speaks (L01 turn 1) → the agent never replies | flow 1 / 0 | judge fail, owner fail |

- **Agreement so far.** Every call here was failed by both raters, so the outcomes agree.
- **What could break that.** In L05, L06 and L07, the non-responsive turns themselves cost little: task 3-4,
  and flow 3-4 in L06/L07. Those calls failed for other reasons (a failed must-pass disclosure check, the
  wrong language, or a low weighted score).
- **Risk to check once 30 labels exist.** An agent that gives the disclosure and speaks the right language,
  but does not answer a caller's question, could still pass with the judge while the owner fails it.

**On (a): "overdue by twelve days".**
- The mock agent says this in L02, L04, L05, L06, L08 and L10 (`mock_agent/policy.py`). It is not in any
  fixture, and the judge scored `factual_accuracy` 4 each time.
- The owner **passed L10**, which contains it. So this unsupported fact alone does not make the owner fail a
  call, and it is not counted as a disagreement.

### To check once L11-L30 are labelled

1. **Non-responsive passes.** For each call the judge passes but the owner fails, is there an unanswered
   caller question? Which dimension did the judge score for it?
2. **Wrong values.** For each owner "wrong value" note, did the judge's `factual_accuracy` drop?
3. **Critical.** On L01-L10 the owner marked 9 calls critical and the judge 4. The owner's critical calls
   include non-responsive ones, which the rubric's critical list (§2.2) does not cover. Settle the
   definition before reading κ on critical.
4. **L10.** It is labelled passed=yes **and** critical=yes; the owner should confirm.
5. **Only if κ < 0.6 on 30 labels (§10.3):** use the disagreements that actually occur to decide on a v2. One
   candidate is an anchor such as "a caller question the agent did not answer caps task_completion at 2".
