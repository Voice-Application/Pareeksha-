# Calibration: judge vs owner labels (FINAL)

**FINAL: all 30 calls labelled by the owner.** Judge: rubric-2026-10-v2.

**HELD-OUT: new calls the v2 rubric was not written from; this is the out-of-sample test of rubric-2026-10-v2.**

Labels: `labelling/EVAL-07/labels.csv` (30 labelled rows, mode **pass_fail_only**), imported as reviewer `preetham` through `POST /calls/{id}/review` (0 posted, 30 already present), then read back from `GET /calibration`.

The owner gave no 0-4 dimension scores, so the reviews were posted without dimensions (no scores were invented) and Spearman / per-dimension MAE are **not provided by owner**.

| metric | GET /calibration | offline recompute (same function, judge_results.json) |
|---|---|---|
| n | 60 | 30 |
| Cohen's kappa (pass/fail) | 0.2873 | 0.0 |
| Spearman rho (overall score) | not provided by owner | not provided by owner |
| MAE per dimension | not provided by owner | not provided by owner |

`GET /calibration` pools every labelled evaluation of the active rubric (n = 60, this batch plus earlier labelled batches); it has no batch filter. **This batch's numbers are the offline column** (same function, this batch's judge rows only).

Target (docs/08 section 10, V9): kappa >= 0.6 on >= 30 calls: **below**.

## Pass/fail (judge rows x owner columns)

| | owner pass | owner fail |
|---|---|---|
| judge pass | 8 | 2 |
| judge fail | 16 | 4 |

Owner passed 24/30, judge passed 10/30. Raw agreement 0.4 (95% Wilson CI [0.2459, 0.5768]); kappa 0.0 (95% percentile bootstrap, calls resampled CI [-0.2448, 0.2222], 10000 resamples, 0.0% of resamples undefined and left out).

## Critical (judge rows x owner columns)

| | owner critical | owner not critical |
|---|---|---|
| judge critical | 3 | 1 |
| judge not critical | 5 | 21 |

Owner critical 8/30, judge critical 4/30. Raw agreement 0.8 (95% Wilson CI [0.6269, 0.9049]); kappa 0.3919 (95% percentile bootstrap, calls resampled CI [-0.0588, 0.7619], 10000 resamples, 0.0% of resamples undefined and left out).

## Inconsistent labels

H15, H21, H27: labelled passed = yes **and** critical = yes (GUIDE.md: a critical call is normally a fail). Counted as written; the owner should confirm.

## Disagreements (18)

Pass/fail or critical differ. Judge reasons are its stored summary plus every dimension it scored below 4.

| label | judge pass/crit/score | owner pass/crit | judge reasons | owner note |
|---|---|---|---|---|
| H01 | False/False/71.25 | True/False | Agent recorded promise-to-pay date and amount correctly via tool, but failed to read back the amount to the caller despite two explicit requests for confirmation. Agent repeated script lines, ignoring caller's question, causing a loop. No policy violations or factual errors. / task_completion 1: Agent recorded PTP date and amount via tool but never read back amount to caller despite caller explicitly asking for confirmation twice (turns 12, 15). Caller's question about amount was ignored; success criteria not fully met. / conversation_flow 1: Agent repeated the same script line (turns 13, 14, 16) after caller asked for amount confirmation, ignoring the question; loop detected. / empathy_tone 3: Agent acknowledged caller's anxiety (turns 3, 5) and offered human help, but later repeated script without addressing caller's specific concern. | - |
| H02 | False/False/68.75 | True/False | Agent recorded correct PTP date and amount but missed mandatory recording disclosure and ignored caller's request to repeat amount. Caller confusion not addressed. / task_completion 3: PTP date and amount recorded correctly, but caller asked for amount repeat in turn 9 and agent did not answer before ending call. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. / conversation_flow 2: Agent ignored caller's request to repeat amount in turn 9 and ended call; also repeated script lines despite caller confusion. / empathy_tone 2: Agent did not acknowledge caller's confusion or hearing difficulty; tone was neutral but not adapted. | - |
| H05 | False/False/86.25 | True/False | Agent handled an angry caller calmly, provided required disclosure, and offered human/callback. However, it repeated the EMI question after the caller said they would not pay, causing a loop. No critical failures. / task_completion 3: Agent acknowledged frustration and offered human/callback, but caller's refusal and statement of non-payment were not fully addressed; agent repeated EMI question after caller said won't pay. / conversation_flow 2: Agent repeated the same EMI question after caller expressed frustration and refusal, causing a loop; otherwise flow was okay. / empathy_tone 3: Agent acknowledged frustration and offered help, but initial responses were scripted and did not directly address caller's anger until later. | Ask why the customer is not willing to pay. Ask, "Okay, then if we can, I'll transfer it. Even so, they can address your issues." It should go on the flow. |
| H06 | False/False/82.5 | True/False | Agent recorded promise-to-pay date (Friday) and amount (4500) via tool call but failed to read back the amount to the caller, missing a key success criterion. All other aspects were compliant and accurate. / task_completion 2: PTP date captured but amount not confirmed with caller; agent did not read back 4500 as required. Caller's request to record date and amount only partially met. / conversation_flow 3: Agent split response across turns 4 and 5, causing slight awkwardness; otherwise flow was smooth. / empathy_tone 3: Agent acknowledged caller's financial tightness with 'I understand' but did not offer further empathy; tone was polite. | - |
| H09 | True/False/100.0 | False/True | Agent successfully repeated EMI due date and amount twice as requested, captured promise to pay, and maintained a patient, compliant interaction. | The agent hallucinated regarding what the customer was asking: "Was it due on the 5th or something like that?" The customer did not confirm that they will pay on the 5th. The agent confirmed that they will be paid on the 5th. |
| H11 | False/False/72.5 | True/False | Agent repeatedly asked for UTR after caller provided it, causing frustration and loop. Caller's request to note UTR was eventually acknowledged, but agent also repeated transfer offer after caller declined. No critical failures. / task_completion 2: Agent repeatedly asked for UTR after caller provided it in turns 7, 9, 11; did not confirm it would be verified until turn 16. Caller's request to note UTR was not explicitly acknowledged until end. / conversation_flow 1: Agent repeated request for UTR after caller provided it multiple times (turns 8, 10), and repeated transfer offer after caller declined (turns 13, 14). Ignored interruptions. / empathy_tone 2: Agent apologized but did not acknowledge caller's frustration; repeated scripted requests despite caller's irritation. / escalation 2: Agent offered transfer twice after caller declined in turn 15; transfer was not needed and caller explicitly refused. | The agent's voice is overlapping now. I think that is not an issue. That is fine. |
| H12 | False/False/61.25 | True/False | Agent successfully recorded promise-to-pay date and amount, but failed to provide mandatory recording disclosure and repeatedly used English/Kannada mix instead of Kannada. Offered transfer after caller declined, causing minor confusion. / policy_compliance 1: Mandatory recording disclosure missing. Agent said 'This call is being recorded for quality and compliance purposes' but not 'for quality purposes' as required. No threats or forbidden content. / language_handling 1: Agent repeatedly replied in English/Kannada mix despite caller speaking Kannada and asking for slower Kannada. Misunderstood caller's request to speak slowly as transfer request. / conversation_flow 2: Agent repeated transfer offer after caller declined, causing confusion. Otherwise flow was coherent. / empathy_tone 2: Agent acknowledged caller's request to speak slowly but did not adapt language; tone neutral, not rude. / escalation 2: Agent offered transfer after caller declined, but caller declined again; no harm done. | - |
| H13 | True/False/95.0 | False/True | Agent correctly declined to waive EMI and late fee, stayed polite, and transferred to human as offered. Disclosures and facts were accurate. Minor friction due to repeated script lines but overall successful. / conversation_flow 3: Agent repeated script lines after caller asked to slow down, causing some friction. No loops or interruptions; pacing was acceptable. / empathy_tone 3: Agent apologized and slowed down when caller asked, but did not explicitly acknowledge confusion. Tone remained polite. | The agent skipped all sentences, so when it is skipped, it went from where it left and |
| H15 | False/False/72.5 | True/True | Agent handled initial greeting and disclosure correctly but failed to complete requested transfer to manager, repeating same line multiple times. Caller's frustration was not adequately addressed, leading to poor conversation flow and unmet escalation. / task_completion 2: Caller's request for manager was acknowledged but transfer not completed; agent repeated same line multiple times. Caller's frustration not addressed beyond apology. / conversation_flow 1: Agent repeated same transfer line multiple times after caller objected; ignored caller's frustration and interruptions. / empathy_tone 2: Agent apologized once but then repeated script without acknowledging caller's anger or frustration. / escalation 2: Transfer initiated in turn 6 but not completed; agent kept repeating transfer line without actually connecting. | - |
| H16 | False/False/62.5 | True/False | Agent accepted UTR and confirmed verification, but failed to answer caller's repeated penalty questions, causing frustration. Mandatory recording disclosure was missing. No factual errors or forbidden content. / task_completion 2: UTR accepted and verification confirmed, but caller's repeated penalty questions were never answered; agent only offered callback or transfer, leaving caller frustrated. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. / conversation_flow 2: Agent repeated same scripted response about UTR and callback despite caller's repeated penalty questions, causing loop-like frustration. / empathy_tone 2: Agent remained polite but did not acknowledge caller's anxiety or frustration, repeating scripted lines. | - |
| H17 | False/False/73.75 | True/False | Caller successfully provided UTR and agent confirmed verification without demanding payment again. However, mandatory recording disclosure was missing and agent used English instead of Kannada. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content. / language_handling 1: Agent replied in English/Kannada mix while caller spoke Kannada; 4/5 agent turns not in Kannada. | - |
| H18 | False/True/43.75 | True/False | Agent failed to transfer caller despite repeated requests. It ignored the first request, then repeated the same transfer line without completing the transfer. Mandatory recording disclosure missing. Caller left frustrated and unanswered. / task_completion 1: Caller requested human in turn 1; agent ignored and repeated greeting in turn 2. Transfer tool called in turn 4 but caller still not transferred; agent repeated same line in turns 6,8,10. Caller's questions about wait time and whether human exists unanswered. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. / language_handling 3: Agent used English, matching caller's light code-mix; understood request for human. Slightly stiff but acceptable. / conversation_flow 1: Agent repeated same script line multiple times after caller objected; ignored interruptions and did not address caller's frustration or questions. / empathy_tone 1: Agent repeated same line to visibly frustrated caller, showing no acknowledgment of emotion or urgency. / escalation 1: Caller requested human in turn 1; agent ignored in turn 2. Transfer tool called in turn 4 but not completed; agent repeated same line in turns 6,8,10, effectively ignoring request multiple times. | - |
| H21 | False/False/83.75 | True/True | Agent correctly repeated due date and amount multiple times, meeting success criteria. However, it ignored caller's interruptions and repeated scripted payment question after caller objected, causing friction. No critical failures. / task_completion 3: Success criteria met: agent repeated due date and amount correctly each time. However, caller's interruptions and repeated requests were not always acknowledged immediately; agent sometimes continued with scripted payment question instead of directly answering. / conversation_flow 2: Agent ignored caller's interruptions (barge-in attempts not honored) and repeated scripted payment question after caller objected. Some turns were not direct responses to caller's latest input. / empathy_tone 2: Agent remained neutral but did not acknowledge caller's frustration or confusion. Repeated scripted lines without adapting to caller's emotional state. | The customer was like, "Okay, tell me the duty again and again." There was no confusion in this call. |
| H25 | False/False/72.5 | True/False | Agent captured promise-to-pay date (Friday) and amount (4500) via tool call but failed to read back the amount to the caller. Caller's confusion about agent identity was not fully addressed. No policy violations. / task_completion 2: PTP date captured but amount not read back to caller; caller's confusion about agent identity was not fully resolved. / factual_accuracy 2: Agent recorded correct amount 4500 but did not read it back; no invented facts. / conversation_flow 2: Agent repeated script lines and did not directly answer caller's confusion about identity; some turns ignored caller's question. / empathy_tone 3: Agent apologized for confusion but did not fully acknowledge caller's confusion; tone was polite. | - |
| H26 | False/False/88.75 | True/False | Agent successfully declined to waive EMI/fee, stayed polite, and offered human transfer. Minor issue: caller's 'are you there?' queries were not directly answered, causing slight friction. Overall correct outcome. / task_completion 3: Success criteria met: agent declined waiver, stayed polite, offered human and payment options. However, caller's repeated 'are you there?' (turns 8, 15, 16) were not directly answered; agent continued with script, causing minor friction. / conversation_flow 2: Agent repeated script lines after caller asked 'are you there?' and did not directly acknowledge those turns. Also, agent's turn 7 was cut off by caller interruption, but agent recovered. | - |
| H27 | False/False/62.5 | True/True | Agent handled the angry caller calmly, acknowledged frustration, and transferred to a human as requested. However, it missed the mandatory recording disclosure and spoke mostly in English instead of Kannada. Minor repetition of the transfer offer caused slight friction. / task_completion 3: Caller's request for human transfer was met, but agent repeated the offer in turn 5 after already asking in turn 4, causing minor friction. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns; no forbidden content. / language_handling 1: Agent replied in English/Kannada mix while caller used Kannada with heavy code-mixing; 4/5 agent turns not in Kannada. / conversation_flow 2: Agent repeated the same offer in consecutive turns, causing a minor loop; otherwise flow was smooth. | - |
| H28 | False/False/73.75 | True/False | Agent successfully handled caller's request for a human agent, transferring immediately. However, mandatory recording disclosure was not properly delivered and agent used English instead of Kannada, causing language mismatch. / policy_compliance 1: Mandatory recording disclosure missing. Agent said 'This call is being recorded for quality and compliance purposes' but deterministic check failed, likely due to language mismatch or mispronunciation. / language_handling 1: Agent replied in English/Kannada mix while caller spoke Kannada. Both agent turns not in Kannada, causing language mismatch. | - |
| H29 | False/False/71.25 | True/False | Agent handled the dispute correctly by not confirming the wrong amount and offering human transfer. However, mandatory recording disclosure was missing. Caller was frustrated but agent remained polite. Transfer was done when requested. / task_completion 3: Agent consistently answered the caller's question about the extra 500 by saying it doesn't have the information and offered human transfer. Caller eventually accepted transfer. No amount confirmed. Minor friction due to repeated offers and caller's frustration. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content. No PII over-collection. / conversation_flow 2: Agent repeated similar script lines multiple times after caller objected, but each time it acknowledged the caller's concern and offered transfer. No loop detected by deterministic check. Some latency and silence gaps. / empathy_tone 3: Agent acknowledged caller's concern ('ನಿಮ್ಮ ಆತಂಕ ಅರ್ಥವಾಗುತ್ತದೆ') but repeated the same phrase, slightly cold. Not dismissive. | - |

## Analysis: v2 over-corrected (DIAGNOSIS ONLY)

**v2 is not adopted on this evidence.** On the 30 held-out calls, `rubric-2026-10-v2` reaches κ = **0.00** (95%
bootstrap CI [−0.24, 0.22]), against 0.61 in-sample.
- The owner passed 24 calls and v2 passed 10.
- 16 of the 18 disagreements are **v2 fail / owner pass**.
- Nothing below was tuned on these labels; the rubric and prompt are unchanged. The counterfactuals are in
  `heldout_ablation.txt`. They rebuild each verdict as `overall ≥ 80 and no blocking review_reason`, which
  matches the stored `passed` on all 60 calls.

### What would move held-out κ (one rule removed at a time, all else as stored)

| removed | held-out κ (agree, v2 passes) | in-sample κ (agree, v2 passes) |
|---|---|---|
| nothing (v2 as stored) | 0.000 (12/30, 10) | 0.609 (27/30, 4) |
| `gate:loop` (largest single gate effect) | 0.048 (14/30, 12) | 0.609 (27/30, 4) |
| `gate:intent_miss` | 0.023 (13/30, 11) | 0.520 (26/30, 5) |
| `gate:intent_miss` + `gate:loop` (= all v2 gates) | 0.074 (15/30, 13) | 0.520 (26/30, 5) |
| `check_failed:disclosure_present` | 0.000 (12/30, 10) | 0.609 (27/30, 4) |
| every check and gate (overall ≥ 80 only) | 0.103 (16/30, 14) | 0.667 (27/30, 6) |

- **No single gate or check explains the gap.** `gate:loop` moves held-out κ the most, but only to 0.05.
  Removing every gate and every must-pass check still leaves κ at 0.10.
- **The scores themselves are too low.** 12 of the 16 owner-pass/v2-fail calls already score **below 80
  overall** (`heldout_ablation.txt`, last block). The v2 anchors and the v2 prompt's responsiveness check cut
  `task_completion`, `conversation_flow` and `empathy_tone` on calls the owner accepts.
- **Why the in-sample calls did not show it.** In the EVAL-06 batch the scripted agent really did ignore
  callers, and the owner failed those calls. The LLM agent here answers far better, and the owner passes 24/30,
  so v2's strictness now produces false fails.
- **Disclosure check: half of its fails are false.** 8 of the 16 calls fail `disclosure_present`:
  - 4 are the `no_disclosure` bug, where the disclosure really is missing.
  - In the 4 `english_to_kannada` calls (H12, H17, H27, H28) the disclosure **was spoken**, in English. Kannada
    STT wrote it in Kannada script ("ದಿಸ್ ಕಾಲ್ ಈಸ್ ಬೀಯಿಂಗ್ ರೆಕಾರ್ಡೆಡ್ / ರೆಕಾರ್ಡರ್ …"), and the agent's disclosure regex
    `(record|ರೆಕಾರ್ಡ್|रिकॉर्ड)` does not match "ರೆಕಾರ್ಡೆ…" / "ರೆಕಾರ್ಡರ್". This is a check defect (ISSUE-4), not the
    owner's policy.
- **The 2 v2-pass / owner-fail calls:**
  - **H09** (clean agent, "Confused about the due date", v2 score 100). The owner notes that the agent confirmed
    a payment on the 5th that the caller never committed to. v2 did not catch an agent **inventing the
    caller's commitment**: its responsiveness check looks for unanswered turns, not for misattributed ones.
  - **H13** (`false_waiver` agent, v2 95). The agent declined the waiver and transferred, so the bug never
    fired. The owner failed it for skipped or cut sentences ("the agent skipped all sentences"), which is an
    audio-continuity problem v2 scored only 3 on flow.

### Owner policy questions this raises (answers needed before any v3)

- **(a) Disclosure.** Is a missing recording / identity disclosure a **fail** for the owner?
  - The owner passed **all 4** `no_disclosure` calls (H02, H16, H18, H29), which really lack it; v1 and v2
    both fail it as a must-pass check. H18 also has a v2 critical failure.
  - Separately, ISSUE-4 must be fixed before this question can be measured cleanly.
- **(b) Flags alone.** Should the `intent_miss` and `loop` flags alone fail a call? The owner passed calls
  carrying them, for example:
  - **H26**, `gate:intent_miss` alone, score 88.75;
  - **H05**, `gate:loop` alone, 86.25;
  - **H21**, `gate:loop` alone, 83.75.

  The EVAL-06 notes asked for responsiveness, but on a responsive agent the owner tolerates the occasional
  missed beat.
- **(c) Invented commitments.** Does confirming a date the caller never gave (**H09**) count as **critical**?
  If yes, it belongs in the critical list as "attributed a commitment the caller did not make", which v2 has
  no rule for.
- **Also for the owner:** H15, H21 and H27 are labelled passed=yes **and** critical=yes (as L10 was). Which
  verdict holds?

### Next step (not done here)

1. Settle (a)-(c) and the 3 inconsistent labels with the owner.
2. Fix ISSUE-4, which is a deterministic check, not the rubric.
3. Any v3 must be checked on a **third**, fresh, owner-labelled batch. The held-out set is now spent for
   tuning purposes.
