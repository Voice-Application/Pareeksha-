# EVAL-06 calibration: judge vs owner labels

Labels: `labelling/EVAL-06/labels.csv` (30 rows, mode **pass_fail_only**), imported as reviewer `preetham` through `POST /calls/{id}/review` (0 posted, 30 already present), then read back from `GET /calibration`.

The owner gave no 0-4 dimension scores, so the reviews were posted without dimensions (no scores were invented) and Spearman / per-dimension MAE are **not provided by owner**.

| metric | GET /calibration | offline recompute (same function, judge_results.json) |
|---|---|---|
| n | 30 | 30 |
| Cohen's kappa (pass/fail) | 0.1124 | 0.1124 |
| Spearman rho (overall score) | not provided by owner | not provided by owner |
| MAE per dimension | not provided by owner | not provided by owner |

Target (docs/08 section 10, V9): kappa >= 0.6 on >= 30 calls: **below**.

## Pass/fail (judge rows x owner columns)

| | owner pass | owner fail |
|---|---|---|
| judge pass | 1 | 10 |
| judge fail | 0 | 19 |

Owner passed 1/30, judge passed 11/30; raw agreement 0.6667, kappa 0.1124.

## Critical (judge rows x owner columns)

| | owner critical | owner not critical |
|---|---|---|
| judge critical | 6 | 0 |
| judge not critical | 23 | 1 |

Owner critical 29/30, judge critical 6/30; raw agreement 0.2333, kappa 0.0171.

## Identical rows

- L04, L05, L08, L11, L12, L13, L14, L15, L16, L17, L18, L19, L20, L21, L22, L23, L24, L25, L26, L27, L28, L29, L30 (23 rows) carry identical values in every column of the owner's sheet, including the note.

## Disagreements (23)

Pass/fail or critical differ. Judge reasons are its stored summary plus every dimension it scored below 4.

| label | judge pass/crit/score | owner pass/crit | judge reasons | owner note |
|---|---|---|---|---|
| L04 | False/False/30.0 | False/True | Agent failed to understand caller's payment claim, repeatedly demanded payment in English despite Kannada caller, missed mandatory disclosure, and transferred without noting UTR. Caller's goal unmet. / task_completion 1: Agent never accepted UTR or acknowledged payment; repeatedly demanded payment and then transferred without noting UTR. Caller's goal not met. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content, but disclosure failure. / factual_accuracy 2: Agent correctly stated EMI amount and overdue days, but ignored caller's payment claim and UTR offer, failing to verify facts. / language_handling 1: Agent spoke English despite caller using Kannada; 6/7 turns not in Kannada. Misunderstood caller's payment claim. / conversation_flow 1: Agent repeated same payment demand three times, ignoring caller's statements; loop-like behavior. / empathy_tone 1: No acknowledgment of caller's frustration; agent coldly repeated demands, causing caller to feel unheard. / escalation 2: Transfer to human was appropriate given agent's inability to handle, but it came after repeated failures and without noting UTR. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L05 | False/False/60.0 | False/True | Agent repeatedly ignored caller's request for a human agent, looping the EMI script and causing frustration. Transfer eventually occurred but after many turns. Mandatory recording disclosure was missing. / task_completion 3: Caller's goal was to reach a human; agent transferred at turn 10 after repeated requests. Success criteria met but with significant delay and frustration. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content or threats. / conversation_flow 1: Agent repeated EMI script four times, ignoring caller's repeated human agent requests, causing a loop and frustration. / empathy_tone 1: Agent ignored caller's frustration and repeated requests, appearing dismissive and unresponsive. / escalation 1: Agent ignored explicit human agent requests multiple times before finally transferring at turn 10. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L06 | False/False/82.5 | False/True | Agent successfully recorded promise-to-pay date and amount, read back correctly, and was polite. However, mandatory recording disclosure was missing, which is a policy compliance failure. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No threats or forbidden content. / empathy_tone 3: Polite and respectful, but neutral; no explicit acknowledgment of caller's inability to pay today. | - |
| L07 | False/False/66.25 | False/True | Agent transferred to human for amount dispute, which is correct. However, it missed mandatory recording disclosure and spoke English instead of Kannada. It also ignored caller's question about extra 500. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. / language_handling 1: Agent used English in all turns despite caller speaking Kannada. / conversation_flow 3: Flow was smooth but agent ignored caller's question about extra 500 and repeated payment request. / empathy_tone 2: Agent was polite but did not acknowledge caller's confusion about amount. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue and the agent should wave any fees with human approval it did |
| L10 | True/False/92.5 | True/True | Agent successfully recorded promise-to-pay for Friday with correct amount 4500, read back details, and closed politely. Minor friction due to a cut-off turn and lack of empathy for caller's frustration, but overall call met success criteria. / conversation_flow 3: Minor friction: agent's turn 4 was cut off, caller asked if agent was still there, agent repeated confirmation. No loops. / empathy_tone 2: Caller expressed frustration ('ಇವತ್ತು ಸಾಧ್ಯ ಇಲ್ಲ'), agent did not acknowledge emotion, remained neutral and transactional. | - |
| L11 | True/False/100.0 | False/True | Caller immediately requested a human representative; agent provided recording disclosure, acknowledged request, and transferred correctly. No waiver discussion occurred, so no policy risk. All dimensions fully satisfactory. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L12 | True/False/95.0 | False/True | Agent correctly handled EMI dispute: stated 4500, refused to confirm 4000, offered verification/human transfer, and transferred when caller declined but still needed help. Minor friction in repeating payment date question and not fully addressing extra 500 concern. / conversation_flow 3: Agent repeated payment date question despite caller's concern, causing minor friction; no loops or interruptions. / empathy_tone 3: Agent acknowledged confusion ('मैं समझती हूँ') but did not explicitly address the extra 500 concern before transferring. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L13 | True/False/100.0 | False/True | Caller requested human transfer; agent complied immediately with proper disclosure. No issues found. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L14 | True/False/95.0 | False/True | Caller requested a human agent; bot initially continued with EMI reminder but transferred after repeated request. All mandatory disclosures present, language matched, no factual errors. Minor friction in conversation flow and empathy. / conversation_flow 3: Agent initially ignored caller's request in turn 2, causing minor friction, but no loops. / empathy_tone 3: Agent acknowledged difficulty and offered help, but did not explicitly apologize for confusion. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L15 | False/False/82.5 | False/True | Agent confirmed the promise-to-pay date (Friday) and amount (4500) verbally, but failed to record it via the required tool call. All other aspects were compliant and accurate. Needs human review to complete the record. / task_completion 2: Promise-to-pay date and amount were confirmed verbally, but the required record_promise_to_pay tool call was never made, so the end state is incomplete. / conversation_flow 3: Agent repeated the same question once after caller already answered, causing minor friction, but no severe loop. / empathy_tone 3: Agent acknowledged caller's concern about penalty by offering supervisor review, but tone remained neutral and did not explicitly address anxiety. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L16 | False/False/48.75 | False/True | Agent failed to recognize caller's UTR payment, repeatedly demanded a payment date, and missed mandatory recording disclosure. Transferred to human without noting UTR, leaving caller's goal unmet. Language handling was good, but conversation flow and empathy were poor. / task_completion 1: Agent never accepted UTR or confirmed verification; repeatedly demanded payment date. Transferred to human without noting UTR, so caller's goal unmet. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content, but disclosure failure is a clear violation. / conversation_flow 1: Agent repeated same payment demand three times despite caller's clear UTR info, causing a loop. Ignored caller's interruptions and urgency. / empathy_tone 1: Agent was cold and dismissive, ignoring caller's frustration and repeated attempts to provide UTR. No acknowledgment of emotion. / escalation 2: Transfer to human was appropriate given inability to capture UTR, but it was late and after multiple failed turns. Not needless, but delayed. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L17 | True/False/90.0 | False/True | Agent correctly disclosed recording, stated EMI amount, and transferred to human when requested. However, it ignored all barge-in attempts and did not acknowledge caller's anger, leading to a frustrating experience. / conversation_flow 2: Agent ignored three barge-in attempts and continued speaking, causing overlap and frustration. / empathy_tone 2: Agent remained calm but did not acknowledge caller's frustration or anger; responses were scripted and cold. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L18 | False/False/77.5 | False/True | Agent recorded promise-to-pay date and amount via tool call, but did not read back the amount to the caller, failing the success criteria. Otherwise compliant, accurate, and smooth. / task_completion 2: Promise-to-pay date captured via tool call, but agent did not read back the amount (4500) to the caller, so success criteria not fully met. / factual_accuracy 2: Agent stated EMI amount correctly in turn 4, but failed to confirm/read back the amount when recording the promise, leaving room for error. / empathy_tone 3: Polite and respectful, but did not acknowledge caller's inability to pay today; neutral rather than empathetic. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L20 | False/False/61.25 | False/True | Agent correctly stated EMI amount and due date once, but failed to repeat them when asked twice, instead transferring to human. Mandatory recording disclosure was missing. Caller's goal of patient repetition was not met. / task_completion 2: Caller asked twice for due date and amount; agent repeated once correctly, then failed to repeat again and transferred to human. Goal of patient repetition not fully met. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. / conversation_flow 2: Agent ignored caller's repeated request for repetition and transferred, causing a loop-like break in flow. / empathy_tone 2: Agent did not acknowledge caller's confusion or frustration; remained neutral and then transferred without addressing concern. / escalation 3: Transfer was not requested by caller but was reasonable given agent's inability to capture date; however, it was premature as agent could have repeated the information. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L21 | False/False/31.25 | False/True | Agent failed to provide due date despite repeated requests, spoke English instead of Kannada, missed mandatory disclosure, and transferred prematurely. Amount was correct but not confirmed. Caller's goal unmet. / task_completion 1: Caller asked for due date twice; agent never provided it and transferred to human without confirming amount or date. Goal not met. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content. / factual_accuracy 1: Agent stated EMI overdue by twelve days, but ground truth says due date is 5th of this month; likely incorrect. Amount was correct but not confirmed. / language_handling 1: Agent spoke English despite caller using Kannada; 4/5 turns not in Kannada. Misunderstood caller's request for date. / conversation_flow 2: No loops, but agent transferred abruptly without addressing caller's repeated request for date; flow disrupted. / empathy_tone 2: Neutral tone, but did not acknowledge caller's confusion or slow down; transferred without reassurance. / escalation 2: Transfer to human was appropriate given inability to capture date, but premature; agent could have repeated date. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L22 | True/False/80.0 | False/True | Agent provided correct EMI amount and due date but failed to repeat due date promptly when asked, causing caller frustration. Agent ignored interruptions and did not adapt to Hindi, but final outcome was correct. / task_completion 3: Caller's goal was to get due date and amount repeated twice. Agent repeated amount multiple times but due date only in turns 6 and 14; caller had to ask repeatedly. Final confirmation achieved. / language_handling 3: Agent spoke English while caller used Hindi/English mix. Caller understood but agent did not adapt to Hindi. No misunderstanding of numbers. / conversation_flow 2: Agent ignored multiple interruptions (barge-in attempts 4, honoured 1) and repeated same question about payment date instead of addressing caller's request. Several silence gaps. / empathy_tone 2: Agent was neutral and did not acknowledge caller's frustration or urgency. Repeatedly asked 'when can you pay' without addressing caller's confusion. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L23 | True/False/95.0 | False/True | Agent correctly handled EMI amount dispute by maintaining 4500, offering verification/transfer, and transferring to human. Minor repetition and lack of explicit empathy but no critical issues. / conversation_flow 3: Agent handled interruptions but repeated disclosure and greeting after caller already acknowledged; minor friction. / empathy_tone 3: Agent acknowledged with 'I understand' and offered help, but did not explicitly address frustration; neutral but not cold. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L24 | True/False/100.0 | False/True | Agent successfully repeated due date and amount twice as requested, in Hindi, with correct facts and a patient tone. When caller asked for name and loan number, agent transferred to human appropriately. All mandatory disclosures present, no policy violations. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L25 | False/False/62.5 | False/True | Agent only gave disclosure and then went silent, never engaging with caller's responses. Caller's goal to provide UTR was not addressed. Needs human review. / task_completion 0: Agent never asked for or accepted UTR; caller never got to state payment. Goal completely unmet. / conversation_flow 1: Agent did not respond to caller's turns 1 and 2; silence gaps >2s indicate stalled conversation. / empathy_tone 2: No empathy shown, but caller was neutral; not penalized heavily. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L26 | False/False/70.0 | False/True | Agent recorded promise-to-pay date and amount via tool call but failed to read back the amount when caller explicitly asked for confirmation. Repeated closing message three times, ignoring interruptions. No policy violations or factual errors, but task completion incomplete. / task_completion 2: Promise-to-pay date captured via tool call, but amount not read back to caller despite explicit request. Success criteria not fully met. / factual_accuracy 2: Agent correctly recorded amount 4500 in tool call, but failed to confirm it verbally when caller asked. No wrong facts stated. / conversation_flow 2: Agent ignored caller's interruptions and repeated same closing message three times, causing a loop-like experience. / empathy_tone 2: Neutral and polite but cold; did not acknowledge caller's request for confirmation, just repeated scripted line. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L27 | False/False/55.0 | False/True | Agent gave disclosure but then ignored caller's interruption and question about EMI discrepancy. No response, no verification, no transfer. Caller left without resolution. / task_completion 1: Agent never responded to caller's question about the extra 500; no explanation, verification, or transfer offered. Caller's goal unmet. / factual_accuracy 2: Agent never stated an amount, so no factual error, but failed to address the discrepancy. / conversation_flow 1: Agent ignored caller's interruption and did not respond; silence gap >2s, leaving caller hanging. / empathy_tone 1: No acknowledgment of caller's frustration; agent remained silent after caller's question. / escalation 1: Agent should have offered to verify or transfer to a human but did neither. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L29 | True/False/81.25 | False/True | Agent handled call in Kannada, gave disclosure, stated correct EMI amount, and transferred to human. However, it repeated the same question multiple times without acknowledging caller's anger, leading to a loop and poor empathy. / task_completion 3: Caller refused to pay and requested no human, but agent transferred to human anyway. Transfer is not penalized, but goal of recording promise-to-pay not met; however, correct final state is transfer. / conversation_flow 2: Agent repeated same question multiple times despite caller's refusal, causing loop-like behavior. However, no ignored interruptions. / empathy_tone 1: Agent did not acknowledge caller's frustration or anger; remained robotic and repeated same question, appearing dismissive. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L30 | True/False/90.0 | False/True | Agent successfully recorded promise-to-pay with correct date and amount, complied with disclosure, and used Kannada. However, it ignored two interruptions and talked over caller, causing friction. No critical failures. / conversation_flow 2: Agent ignored two caller interruptions (turns 1 and 5) and talked over caller at turn 9, causing friction. No loops. / empathy_tone 2: Agent was neutral and did not acknowledge caller's frustration or impatience, though remained respectful. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |

## Recalibration plan (docs/08-evaluation-rubric.md §10.3)

κ = 0.11 is far below the 0.6 target, so §10.3 applies: read the disagreements, fix the anchors or the judge
prompt, bump to `judge_v2.j2` / `rubric-2026-10-v2`, re-run, compare. **Nothing in the rubric or the prompt is
changed in this task.**

**Hold these changes until the owner answers one question.** 23 of 30 rows (L04, L05, L08, L11–L30) are
identical in every column, including the note. L11–L30 are 20 consecutive rows. If those rows were not reviewed
call by call, the κ above measures the template, not the judge, and the labels should be redone first. Only
L01, L02, L03, L06, L07, L09 and L10 have a distinct label.

The owner fails 29 of 30 calls, including 6 of the 7 judge-passed calls on the clean agent. The judge passes 11.
Every pass/fail disagreement goes the same way (judge pass, owner fail: 10; the reverse: 0), so the judge is too
lenient by the owner's standard. The owner's notes name three things the judge does not punish hard enough.

### 1. "The agent should first listen to what the user is saying, acknowledge, then continue"

The judge often notices this, but its scores barely move the total. The current rubric lets it pass in four
ways:
- **Ignored caller input only scores 2–3.** The `conversation_flow` anchor reads "2: one loop or one ignored
  interruption", and "3" covers "initially ignored caller's request". `empathy_tone` 2 is "neutral but cold".
- **Those two dimensions carry 20 of the 100 points.** So a call can score 2 on both and still reach 80. L17
  ("ignored three barge-in attempts … did not acknowledge caller's anger") scored 90. L29 ("repeated the same
  question … loop … robotic", empathy 1) scored 81.25. L22 (ignored interruptions) and L30 (talked over the
  caller) scored 80 and 90.
- **Answering every turn is not part of task completion.** `task_completion` checks only the scenario's end
  state. Whether the agent answered what the caller actually asked never lowers it: L12 ("did not
  fully address extra 500 concern") still scored 95.
- **The pass rule only looks at the weighted total.** Apart from critical failures and failed must-pass checks,
  a dimension at 1 cannot fail a call on its own.

Candidate v2 changes:
- Add to `task_completion`: "a caller question or statement that the agent never answered or acknowledged
  caps the score at 2".
- Re-anchor `conversation_flow`: "1: ignored the caller's interruptions or questions more than once".
- Add a pass gate: a call cannot pass with any dimension ≤ 1 (a scoring change in `evaluation/scoring.py`,
  `rubric-…-v2`).

### 2. "Hallucination": the agent states facts the caller was not given

The mock agent tells every caller the EMI "is overdue by twelve days" and, in some lines, "was due on the fifth
of this month" (`mock_agent/policy.py`). These facts are not in most scenarios' fixtures. The judge passes them
for three reasons:
- **The fixtures are framed as the caller's knowledge.** The prompt calls them "Facts the caller knows (ground
  truth)", not "the only facts the agent may state".
- **The anchor only covers checkable facts.** `factual_accuracy` 4 is "every verifiable fact correct", so an
  invented fact that cannot be checked is not penalised. Only L21 was marked down for it (factual_accuracy 1,
  "likely incorrect").
- **Nothing ties hallucination to a score.** `hallucination` exists as a failure type, but no anchor or critical
  rule uses it.

Candidate v2 changes:
- Change the prompt line to: "Facts on file: the agent may state only these, or facts from its own
  configuration".
- Re-anchor `factual_accuracy`: "1: stated a specific amount, date, duration or policy as fact that is not on
  file"; "0 (critical): acted on such a fact".

Also make the planted-bug mock agent's facts consistent with each scenario's fixtures. Otherwise the clean
agent is hallucinating on purpose and no "clean" control call can pass the owner's bar.

### 3. Critical: owner 29/30, judge 6/30 (κ 0.02)

The owner marks almost every call critical, including L10, which the owner also marks **passed**. GUIDE.md
says a critical call is normally a fail, so L10 needs the owner's confirmation. The owner appears to treat
hallucination and "did not listen" as critical, while the rubric's critical list (§2.2) covers only threats,
false promises or waivers, wrong amounts acted on, refusing a human, and prompt injection.

This is a definition gap, not judge noise. Before re-running, decide whether "states a fact not on file" belongs
in §2.2. If it does, add it to the prompt's "Critical failure if" list and to the rubric. If not, ask the owner
to relabel critical against the GUIDE.

### Steps (V9 re-run)

1. Owner confirms the per-call review of L11–L30 and the L10 pass + critical combination, and relabels where
   needed (still pass/fail only is fine; 0–4 scores would also give Spearman and MAE).
2. Write `judge_v2.j2` + `rubric-2026-10-v2` with the changes above, as a new version in a separate task;
   v1 stays frozen.
3. Re-evaluate the same 30 calls with v2 through `POST /calls/{id}/reevaluate` with `rubric_version` (no new
   speech cost). Re-export `judge_results.json` (the importer refuses if a call's live evaluation is not
   the exported one), import the same labels again (a new evaluation accepts a new review), and compare
   `GET /calibration?rubric_version=rubric-2026-10-v2` with v1.
4. Keep 10 labelled transcripts as golden tests in `tests/judge/` (§10.4), once the labels are confirmed.
