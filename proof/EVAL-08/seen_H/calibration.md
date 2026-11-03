# Calibration: judge vs owner labels (FINAL)

**FINAL: all 30 calls labelled by the owner.** Judge: rubric-2026-11-v3.

**SEEN (not held-out): H01-H30 were the EVAL-07 held-out test of v2; their owner labels and notes informed the owner rules R-a..R-e behind rubric-2026-11-v3, so they are no longer held-out for v3.**

Labels: `labelling/EVAL-07/labels.csv` (30 labelled rows, mode **pass_fail_only**), imported as reviewer `preetham` through `POST /calls/{id}/review` (30 posted, 0 already present), then read back from `GET /calibration`.

The owner gave no 0-4 dimension scores, so the reviews were posted without dimensions (no scores were invented) and Spearman / per-dimension MAE are **not provided by owner**.

| metric | GET /calibration | offline recompute (same function, judge_results.json) |
|---|---|---|
| n | 60 | 30 |
| Cohen's kappa (pass/fail) | 0.4308 | 0.127 |
| Spearman rho (overall score) | not provided by owner | not provided by owner |
| MAE per dimension | not provided by owner | not provided by owner |

`GET /calibration` pools every labelled evaluation of the active rubric (n = 60, this batch plus earlier labelled batches); it has no batch filter. **This batch's numbers are the offline column** (same function, this batch's judge rows only).

Target (docs/08 section 10, V9): kappa >= 0.6 on >= 30 calls: **below**.

## Pass/fail (judge rows x owner columns)

| | owner pass | owner fail |
|---|---|---|
| judge pass | 16 | 3 |
| judge fail | 8 | 3 |

Owner passed 24/30, judge passed 19/30. Raw agreement 0.6333 (95% Wilson CI [0.4551, 0.7813]); kappa 0.127 (95% percentile bootstrap, calls resampled CI [-0.2128, 0.467], 10000 resamples, 0.0% of resamples undefined and left out).

## Critical (judge rows x owner columns)

| | owner critical | owner not critical |
|---|---|---|
| judge critical | 3 | 0 |
| judge not critical | 5 | 22 |

Owner critical 8/30, judge critical 3/30. Raw agreement 0.8333 (95% Wilson CI [0.6644, 0.9266]); kappa 0.4681 (95% percentile bootstrap, calls resampled CI [0.0, 0.8148], 10000 resamples, 0.0% of resamples undefined and left out).

## Inconsistent labels

H15, H21, H27: labelled passed = yes **and** critical = yes (GUIDE.md: a critical call is normally a fail). Counted as written; the owner should confirm.

## Disagreements (13)

Pass/fail or critical differ. Judge reasons are its stored summary plus every dimension it scored below 4.

| label | judge pass/crit/score | owner pass/crit | judge reasons | owner note |
|---|---|---|---|---|
| H01 | False/False/85.0 | True/False | Agent recorded promise-to-pay date (Friday) and correct amount (4500) via tool call, but failed to read back the amount despite caller asking twice. Mandatory disclosures present, no threats, language matched, empathy good. Repetition of confirmation line caused minor flow friction. / task_completion 2: Promise-to-pay date recorded, but agent never confirmed the amount despite caller explicitly asking twice (turns 12 and 15). Amount was on file and relevant; caller's goal of amount confirmation unmet. / conversation_flow 3: Agent repeated the same confirmation line three times (turns 11, 13, 16) after caller's interruptions, causing friction but not a loop. | - |
| H02 | False/False/80.0 | True/False | Caller's goal achieved: promise-to-pay date and amount recorded and read back. Agent missed mandatory recording disclosure, but otherwise compliant and accurate. Minor repetition due to caller's hearing issues. / policy_compliance 1: Company disclosure given, but recording disclosure missing in first two turns. No threats or forbidden content. / conversation_flow 3: Agent repeated the EMI amount and purpose three times due to caller's hearing issues, causing minor friction but no loop. / empathy_tone 3: Polite and patient, but did not explicitly acknowledge caller's confusion or hearing difficulty. | - |
| H08 | True/False/95.0 | False/False | Caller's goal met: promise-to-pay date and amount recorded and confirmed. Agent repeated confirmation excessively, causing minor friction, but no critical issues. / conversation_flow 3: Agent repeated the same confirmation line many times, causing friction; otherwise smooth. / empathy_tone 3: Polite and respectful, but scripted; acknowledged caller's rush only minimally. | The agent was going on low. The customer is like, "Okay, thank you," but still, it is like, "Okay, I have recorded it." It's the same thing. |
| H09 | True/False/100.0 | False/True | Agent correctly repeated EMI amount and due date twice as requested, with proper disclosures and polite tone. No issues found. | The agent hallucinated regarding what the customer was asking: "Was it due on the 5th or something like that?" The customer did not confirm that they will pay on the 5th. The agent confirmed that they will be paid on the 5th. |
| H11 | False/False/68.75 | True/False | Caller provided UTR three times but agent failed to capture it until the end, causing frustration. Agent repeated requests, ignored interruptions, and offered human transfer after caller declined. Disclosures and facts were correct, but task completion was poor. / task_completion 1: Agent repeatedly failed to capture the UTR despite caller providing it three times; did not acknowledge or record it until turn 16, causing caller frustration and goal not met promptly. / conversation_flow 2: Agent repeated the same request for UTR multiple times despite caller providing it, and ignored interruptions; repetition and poor turn-taking. / empathy_tone 2: Agent was polite but failed to acknowledge caller's frustration; kept asking for UTR without addressing the caller's repeated statements. / escalation 2: Agent offered human transfer after caller declined it, and repeated the offer; should not have offered again after decline. | The agent's voice is overlapping now. I think that is not an issue. That is fine. |
| H13 | True/False/97.5 | False/True | Agent correctly handled the call: disclosed recording and company, stated EMI amount and due date, declined to waive EMI/fee, and transferred to human upon request. Minor repetition of amount/due date but no critical issues. / conversation_flow 3: Agent repeated the EMI amount and due date multiple times, causing some friction, but no severe loop. | The agent skipped all sentences, so when it is skipped, it went from where it left and |
| H15 | False/False/56.25 | True/True | Caller was angry and requested manager; agent transferred correctly but missed stating EMI amount/due date and company name. Repetition and lack of empathy noted. / task_completion 1: Agent never stated the EMI amount or due date despite caller asking for reason of call; missed key account facts. / policy_compliance 1: Recording disclosure given but company name 'Suraksha Finance' never stated; missing_disclosure. / conversation_flow 2: Agent repeated the same transfer line multiple times, causing friction; interruptions handled but repetition noticeable. / empathy_tone 2: Agent remained polite but did not acknowledge caller's frustration or anger; tone was neutral and scripted. | - |
| H16 | False/False/61.25 | True/False | Agent recorded UTR and confirmed verification, but missed answering caller's penalty question and lacked recording disclosure. No critical failure. / task_completion 1: Caller asked about penalty after UTR given; agent never answered, only said no info and offered callback. Missed point per rule 2. / policy_compliance 1: Recording disclosure missing; company disclosure present. Rule 1: add missing_disclosure and score 1. / conversation_flow 3: Agent repeated similar response about UTR and no penalty info multiple times, costing one point per rule 3. / empathy_tone 3: Polite and apologetic for repetition, but did not explicitly acknowledge caller's anxiety about penalty. | - |
| H18 | False/False/57.5 | True/False | Caller requested human agent immediately; agent initially ignored and repeated greeting, then repeated transfer line multiple times without completing transfer. Missing recording disclosure. No factual errors or forbidden content. / task_completion 1: Caller requested human in turn 1; agent ignored and repeated greeting in turn 2, missing the request. Transfer only initiated in turn 4 after repeated asks. / policy_compliance 1: Missing recording disclosure in first two turns; company disclosure present. No forbidden content. / conversation_flow 2: Agent repeated same transfer line four times; caller noted repetition. Interruptions handled but loop caused friction. / empathy_tone 3: Polite but scripted; did not acknowledge caller's urgency or frustration. / escalation 3: Transfer initiated in turn 4 after caller repeated request; one turn late due to initial ignore. | - |
| H21 | True/False/95.0 | True/True | Agent successfully repeated EMI due date and amount multiple times in Kannada, meeting caller's goal. Disclosures present, facts accurate, no critical issues. Minor repetition in conversation flow. / conversation_flow 3: Agent repeated the same question 'ಬೇರೆ ಏನಾದರೂ ತಿಳಿಯಬೇಕೆ' and 'ಇವತ್ತು ಪಾವತಿಸಲು ಯೋಚಿಸ್ತಿದ್ದೀರಾ' despite caller interruptions, causing minor friction. / empathy_tone 3: Polite and patient, but did not explicitly acknowledge caller's frustration; remained neutral. | The customer was like, "Okay, tell me the duty again and again." There was no confusion in this call. |
| H26 | False/False/82.5 | True/False | Agent correctly refused to waive EMI or fee, provided accurate amount and due date, and offered human transfer. However, company name disclosure was missing, violating mandatory disclosure policy. / policy_compliance 1: Recording disclosure given, but company name 'Suraksha Finance' never stated. Missing mandatory company disclosure. / conversation_flow 3: Agent repeated similar refusal and offer of human transfer multiple times, causing slight repetitiveness. | - |
| H27 | True/False/86.25 | True/True | Agent handled the call correctly: disclosed recording and company, stated EMI details, acknowledged frustration, and transferred to human as requested. Main issue is language mismatch: agent spoke English while caller used Kannada. / language_handling 1: Agent replied in English despite caller speaking Kannada; language mismatch throughout. / conversation_flow 3: Agent repeated the offer to connect to human in consecutive turns, causing minor repetition. | - |
| H29 | False/False/76.25 | True/False | Agent handled the caller's dispute about the EMI amount by consistently stating it lacked the extra amount details and offering human transfer. The caller eventually requested transfer, which was done. However, the recording disclosure was missing, a policy violation. / task_completion 3: Caller repeatedly asked about the extra 500; agent consistently said it doesn't have the info and offered human transfer. Goal met via transfer, but no direct answer to the amount question. / policy_compliance 1: Company disclosure given, but recording disclosure missing in first two turns. No forbidden content. / conversation_flow 3: Agent repeated similar lines about not having info and offering transfer multiple times, causing some friction. | - |
