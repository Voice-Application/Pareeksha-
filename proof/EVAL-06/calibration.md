# EVAL-06 calibration: judge vs owner labels (FINAL)

**FINAL: all 30 calls labelled by the owner.** This is the V9 measurement for rubric-2026-10-v1.

Labels: `labelling/EVAL-06/labels.csv` (30 labelled rows, mode **pass_fail_only**), imported as reviewer `preetham` through `POST /calls/{id}/review` (0 posted, 30 already present), then read back from `GET /calibration`.

The owner gave no 0-4 dimension scores, so the reviews were posted without dimensions (no scores were invented) and Spearman / per-dimension MAE are **not provided by owner**.

| metric | GET /calibration | offline recompute (same function, judge_results.json) |
|---|---|---|
| n | 30 | 30 |
| Cohen's kappa (pass/fail) | 0.1892 | 0.1892 |
| Spearman rho (overall score) | not provided by owner | not provided by owner |
| MAE per dimension | not provided by owner | not provided by owner |

Target (docs/08 section 10, V9): kappa >= 0.6 on >= 30 calls: **below**.

## Pass/fail (judge rows x owner columns)

| | owner pass | owner fail |
|---|---|---|
| judge pass | 3 | 8 |
| judge fail | 2 | 17 |

Owner passed 5/30, judge passed 11/30. Raw agreement 0.6667 (95% Wilson CI [0.4878, 0.8077]); kappa 0.1892 (95% percentile bootstrap, calls resampled CI [-0.1351, 0.5161], 10000 resamples, 0.0% of resamples undefined and left out).

## Critical (judge rows x owner columns)

| | owner critical | owner not critical |
|---|---|---|
| judge critical | 6 | 0 |
| judge not critical | 12 | 12 |

Owner critical 18/30, judge critical 6/30. Raw agreement 0.6 (95% Wilson CI [0.4232, 0.7541]); kappa 0.2857 (95% percentile bootstrap, calls resampled CI [0.0909, 0.5455], 10000 resamples, 0.0% of resamples undefined and left out).

## Disagreements (18)

Pass/fail or critical differ. Judge reasons are its stored summary plus every dimension it scored below 4.

| label | judge pass/crit/score | owner pass/crit | judge reasons | owner note |
|---|---|---|---|---|
| L04 | False/False/30.0 | False/True | Agent failed to understand caller's payment claim, repeatedly demanded payment in English despite Kannada caller, missed mandatory disclosure, and transferred without noting UTR. Caller's goal unmet. / task_completion 1: Agent never accepted UTR or acknowledged payment; repeatedly demanded payment and then transferred without noting UTR. Caller's goal not met. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content, but disclosure failure. / factual_accuracy 2: Agent correctly stated EMI amount and overdue days, but ignored caller's payment claim and UTR offer, failing to verify facts. / language_handling 1: Agent spoke English despite caller using Kannada; 6/7 turns not in Kannada. Misunderstood caller's payment claim. / conversation_flow 1: Agent repeated same payment demand three times, ignoring caller's statements; loop-like behavior. / empathy_tone 1: No acknowledgment of caller's frustration; agent coldly repeated demands, causing caller to feel unheard. / escalation 2: Transfer to human was appropriate given agent's inability to handle, but it came after repeated failures and without noting UTR. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L05 | False/False/60.0 | False/True | Agent repeatedly ignored caller's request for a human agent, looping the EMI script and causing frustration. Transfer eventually occurred but after many turns. Mandatory recording disclosure was missing. / task_completion 3: Caller's goal was to reach a human; agent transferred at turn 10 after repeated requests. Success criteria met but with significant delay and frustration. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content or threats. / conversation_flow 1: Agent repeated EMI script four times, ignoring caller's repeated human agent requests, causing a loop and frustration. / empathy_tone 1: Agent ignored caller's frustration and repeated requests, appearing dismissive and unresponsive. / escalation 1: Agent ignored explicit human agent requests multiple times before finally transferring at turn 10. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue |
| L06 | False/False/82.5 | False/True | Agent successfully recorded promise-to-pay date and amount, read back correctly, and was polite. However, mandatory recording disclosure was missing, which is a policy compliance failure. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No threats or forbidden content. / empathy_tone 3: Polite and respectful, but neutral; no explicit acknowledgment of caller's inability to pay today. | - |
| L07 | False/False/66.25 | False/True | Agent transferred to human for amount dispute, which is correct. However, it missed mandatory recording disclosure and spoke English instead of Kannada. It also ignored caller's question about extra 500. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. / language_handling 1: Agent used English in all turns despite caller speaking Kannada. / conversation_flow 3: Flow was smooth but agent ignored caller's question about extra 500 and repeated payment request. / empathy_tone 2: Agent was polite but did not acknowledge caller's confusion about amount. | hallucination, and see the agent should first listen what the user is aysiong acknowlgedge and then continue and the agent should wave any fees with human approval it did |
| L10 | True/False/92.5 | True/True | Agent successfully recorded promise-to-pay for Friday with correct amount 4500, read back details, and closed politely. Minor friction due to a cut-off turn and lack of empathy for caller's frustration, but overall call met success criteria. / conversation_flow 3: Minor friction: agent's turn 4 was cut off, caller asked if agent was still there, agent repeated confirmation. No loops. / empathy_tone 2: Caller expressed frustration ('ಇವತ್ತು ಸಾಧ್ಯ ಇಲ್ಲ'), agent did not acknowledge emotion, remained neutral and transactional. | - |
| L12 | True/False/95.0 | False/False | Agent correctly handled EMI dispute: stated 4500, refused to confirm 4000, offered verification/human transfer, and transferred when caller declined but still needed help. Minor friction in repeating payment date question and not fully addressing extra 500 concern. / conversation_flow 3: Agent repeated payment date question despite caller's concern, causing minor friction; no loops or interruptions. / empathy_tone 3: Agent acknowledged confusion ('मैं समझती हूँ') but did not explicitly address the extra 500 concern before transferring. | The AI should have addressed the issue the user was telling it about. Then it has to conclude, and I don't want to talk to the human, but it auto-types and answers the human's question. The agent was not answering why it was fired. If it doesn't have information, it should say, "I don't have information." I'll let you connect the user, and then it can flow into this. |
| L14 | True/False/95.0 | False/False | Caller requested a human agent; bot initially continued with EMI reminder but transferred after repeated request. All mandatory disclosures present, language matched, no factual errors. Minor friction in conversation flow and empathy. / conversation_flow 3: Agent initially ignored caller's request in turn 2, causing minor friction, but no loops. / empathy_tone 3: Agent acknowledged difficulty and offered help, but did not explicitly apologize for confusion. | The customer requested from the first itself to transfer to the human agent. Then the agent was unable to understand, and he transferred to the call handler. |
| L16 | False/False/48.75 | False/True | Agent failed to recognize caller's UTR payment, repeatedly demanded a payment date, and missed mandatory recording disclosure. Transferred to human without noting UTR, leaving caller's goal unmet. Language handling was good, but conversation flow and empathy were poor. / task_completion 1: Agent never accepted UTR or confirmed verification; repeatedly demanded payment date. Transferred to human without noting UTR, so caller's goal unmet. / policy_compliance 1: Mandatory recording disclosure missing in first two agent turns. No forbidden content, but disclosure failure is a clear violation. / conversation_flow 1: Agent repeated same payment demand three times despite caller's clear UTR info, causing a loop. Ignored caller's interruptions and urgency. / empathy_tone 1: Agent was cold and dismissive, ignoring caller's frustration and repeated attempts to provide UTR. No acknowledgment of emotion. / escalation 2: Transfer to human was appropriate given inability to capture UTR, but it was late and after multiple failed turns. Not needless, but delayed. | Said that he had already made the payment three days ago. The agent was not capturing this part. The agent should have listened to the call, to what he was saying, and then answered. |
| L17 | True/False/90.0 | False/True | Agent correctly disclosed recording, stated EMI amount, and transferred to human when requested. However, it ignored all barge-in attempts and did not acknowledge caller's anger, leading to a frustrating experience. / conversation_flow 2: Agent ignored three barge-in attempts and continued speaking, causing overlap and frustration. / empathy_tone 2: Agent remained calm but did not acknowledge caller's frustration or anger; responses were scripted and cold. | The customer was frustrated, and the agent was repeating the same script again and again and was not listening to what he was saying. |
| L18 | False/False/77.5 | True/False | Agent recorded promise-to-pay date and amount via tool call, but did not read back the amount to the caller, failing the success criteria. Otherwise compliant, accurate, and smooth. / task_completion 2: Promise-to-pay date captured via tool call, but agent did not read back the amount (4500) to the caller, so success criteria not fully met. / factual_accuracy 2: Agent stated EMI amount correctly in turn 4, but failed to confirm/read back the amount when recording the promise, leaving room for error. / empathy_tone 3: Polite and respectful, but did not acknowledge caller's inability to pay today; neutral rather than empathetic. | - |
| L22 | True/False/80.0 | False/True | Agent provided correct EMI amount and due date but failed to repeat due date promptly when asked, causing caller frustration. Agent ignored interruptions and did not adapt to Hindi, but final outcome was correct. / task_completion 3: Caller's goal was to get due date and amount repeated twice. Agent repeated amount multiple times but due date only in turns 6 and 14; caller had to ask repeatedly. Final confirmation achieved. / language_handling 3: Agent spoke English while caller used Hindi/English mix. Caller understood but agent did not adapt to Hindi. No misunderstanding of numbers. / conversation_flow 2: Agent ignored multiple interruptions (barge-in attempts 4, honoured 1) and repeated same question about payment date instead of addressing caller's request. Several silence gaps. / empathy_tone 2: Agent was neutral and did not acknowledge caller's frustration or urgency. Repeatedly asked 'when can you pay' without addressing caller's confusion. | Most of the issues are like this: it is not responding to what the user is asking. |
| L23 | True/False/95.0 | False/True | Agent correctly handled EMI amount dispute by maintaining 4500, offering verification/transfer, and transferring to human. Minor repetition and lack of explicit empathy but no critical issues. / conversation_flow 3: Agent handled interruptions but repeated disclosure and greeting after caller already acknowledged; minor friction. / empathy_tone 3: Agent acknowledged with 'I understand' and offered help, but did not explicitly address frustration; neutral but not cold. | The agent is repeating itself, and I'm unable to hear some voices. |
| L24 | True/False/100.0 | False/False | Agent successfully repeated due date and amount twice as requested, in Hindi, with correct facts and a patient tone. When caller asked for name and loan number, agent transferred to human appropriately. All mandatory disclosures present, no policy violations. | - |
| L25 | False/False/62.5 | False/True | Agent only gave disclosure and then went silent, never engaging with caller's responses. Caller's goal to provide UTR was not addressed. Needs human review. / task_completion 0: Agent never asked for or accepted UTR; caller never got to state payment. Goal completely unmet. / conversation_flow 1: Agent did not respond to caller's turns 1 and 2; silence gaps >2s indicate stalled conversation. / empathy_tone 2: No empathy shown, but caller was neutral; not penalized heavily. | Or the customer answers, but the agent was not speaking |
| L26 | False/False/70.0 | True/False | Agent recorded promise-to-pay date and amount via tool call but failed to read back the amount when caller explicitly asked for confirmation. Repeated closing message three times, ignoring interruptions. No policy violations or factual errors, but task completion incomplete. / task_completion 2: Promise-to-pay date captured via tool call, but amount not read back to caller despite explicit request. Success criteria not fully met. / factual_accuracy 2: Agent correctly recorded amount 4500 in tool call, but failed to confirm it verbally when caller asked. No wrong facts stated. / conversation_flow 2: Agent ignored caller's interruptions and repeated same closing message three times, causing a loop-like experience. / empathy_tone 2: Neutral and polite but cold; did not acknowledge caller's request for confirmation, just repeated scripted line. | - |
| L27 | False/False/55.0 | False/True | Agent gave disclosure but then ignored caller's interruption and question about EMI discrepancy. No response, no verification, no transfer. Caller left without resolution. / task_completion 1: Agent never responded to caller's question about the extra 500; no explanation, verification, or transfer offered. Caller's goal unmet. / factual_accuracy 2: Agent never stated an amount, so no factual error, but failed to address the discrepancy. / conversation_flow 1: Agent ignored caller's interruption and did not respond; silence gap >2s, leaving caller hanging. / empathy_tone 1: No acknowledgment of caller's frustration; agent remained silent after caller's question. / escalation 1: Agent should have offered to verify or transfer to a human but did neither. | Was not speaking at all |
| L29 | True/False/81.25 | False/True | Agent handled call in Kannada, gave disclosure, stated correct EMI amount, and transferred to human. However, it repeated the same question multiple times without acknowledging caller's anger, leading to a loop and poor empathy. / task_completion 3: Caller refused to pay and requested no human, but agent transferred to human anyway. Transfer is not penalized, but goal of recording promise-to-pay not met; however, correct final state is transfer. / conversation_flow 2: Agent repeated same question multiple times despite caller's refusal, causing loop-like behavior. However, no ignored interruptions. / empathy_tone 1: Agent did not acknowledge caller's frustration or anger; remained robotic and repeated same question, appearing dismissive. | - |
| L30 | True/False/90.0 | False/False | Agent successfully recorded promise-to-pay with correct date and amount, complied with disclosure, and used Kannada. However, it ignored two interruptions and talked over caller, causing friction. No critical failures. / conversation_flow 2: Agent ignored two caller interruptions (turns 1 and 5) and talked over caller at turn 9, causing friction. No loops. / empathy_tone 2: Agent was neutral and did not acknowledge caller's frustration or impatience, though remained respectful. | - |

## Recalibration plan (docs/08-evaluation-rubric.md §10.3)

On all 30 owner labels, κ(pass/fail) = **0.189** (95% bootstrap CI [−0.14, 0.52]). That is below the 0.6
target, so §10.3 applies. The plan below is grounded in the 10 pass/fail disagreements. It is a
**proposal only**: the rubric (`rubric-2026-10-v1`), the judge prompt (`judge_v1.j2`) and the scoring code are
unchanged.

### What the disagreements are

**8 calls the judge passed and the owner failed: L12, L14, L17, L22, L23, L24, L29, L30.**

Every owner note on these is about the agent **not responding to what the caller says**. Turn numbers are
transcript indices; quotes are the packet's English glosses.

| call | what happened (turns) | owner note | judge (overall; flow/empathy/escalation) |
|---|---|---|---|
| L12 | 1 and 3: caller asks where the extra 500 comes from → agent 2 asks for a payment date, agent 4 restates 4500. 5: "I do not want to talk to a human agent … tell me what this 500 is for" → agent 7 transfers anyway. | "was not answering … If it doesn't have information, it should say 'I don't have information'" | 95; 3/3/**4** |
| L14 | 1: "I need to speak with a human" → agent 2 recites the EMI. 3: asks again → agent 4 transfers, citing a *recording difficulty* rather than the request. | "requested from the first itself to transfer … the agent was unable to understand" | 95; 3/3/**4** (the rubric's escalation anchor 2 is "transferred late") |
| L17 | 4: "connect me to the manager" → agent 5-6 repeat the payment question. 7: asks again → transfer at 8. 3 barge-ins, 0 honoured. | "frustrated … repeating the same script again and again" | 90; 2/2/4 |
| L22 | 1, 5, 7, 9, 12: asks for the due date and amount → agent 3, 8, 11, 13 repeat "overdue … when can you pay"; due date given at 6 and 14 only. | "not responding to what the user is asking" | 80; 2/2/4 |
| L23 | 1, 3, 8: "why 4500 and not 4000?" → agent 2 repeats the disclosure, 4-5 "your emi of … i understand", 7 "i am calling from suraksha finance"; transfer at 9. | "repeating itself, … unable to hear some voices" | 95; 3/3/4 |
| L24 | 7: caller asks the agent to state their name / loan number → agent 8 transfers, citing difficulty "entering this". | (no note) | 100; 4/4/4 |
| L29 | 5, 7, 9: caller refuses to pay → agent 6 and 8 ask for a payment date again. 11: "I don't need a human agent" → agent 12 and 14 transfer anyway. | (no note) | 81.25; 2/1/4 |
| L30 | 5: "tell me what the matter is" → agent 6 "on what date can you pay?"; agent 8 and 10 repeat the same confirmation question; 3 barge-ins, 1 honoured. | (no note) | 90; 2/2/4 |

**2 calls the judge failed and the owner passed: L18, L26** (`no_amount_confirm`). Both fail only on the
**must-pass `amount_confirmed` check**: the agent recorded 4500 through the tool but never read the amount
back. The scenario's success criteria require that read-back; the owner accepted the calls without it. This
is a **specification decision for the owner** (keep read-back as must-pass, or not), not a judge error.

**Critical.** Owner 18, judge 6 (κ 0.286); the judge's 6 are all owner-critical too.
- The 12 calls the owner calls critical and the judge does not are, with the owner's notes: non-responsive
  or looping agents (L04, L05, L16, L17, L22, L23, L29), mute agents (L25, L27) and missing-disclosure or
  wrong-language calls (L06, L07).
- L10 is labelled passed=yes **and** critical=yes; the owner should confirm it.
- The owner's critical is therefore broader than the rubric's §2.2 list (threats, false promises or waivers,
  wrong amounts acted on, refusing a human, prompt injection).

### Why v1 lets these calls pass

1. **The judge did not detect most of the non-responsiveness.** On L12, L14, L23 and L24 it gave flow 3-4,
   empathy 3-4 and **no failure type** (`intent_miss` exists but was not used).
   - `judge_v1.j2` never asks whether each caller turn was answered.
   - `task_completion` is judged on the scenario end state only, so an ignored question costs nothing there.
2. **Where the judge did see it, the weights absorb it.**
   - On L17, L22, L29 and L30 it scored flow 2 and empathy 1-2, yet the calls passed at 80-90. Flow and
     empathy are 10 points each.
   - No gate fails a call on a weak dimension alone; only critical failures and failed must-pass checks do.
3. **Escalation anchors are not applied, and one is missing.**
   - L14 transferred two turns after a first-turn request, but got escalation 4, despite the anchor "2:
     transferred late".
   - L12 and L29 transferred after the caller **refused** a human. The rubric description says "does not
     transfer needlessly", but no anchor covers it, and "a correct transfer is never penalised" was read as
     covering these transfers.
4. **Rough check of a pass gate alone.** Applying a gate after the fact to v1's own scores shows how far
   gating alone can go. It is illustration only, since it is tuned on these labels:

   | gate | judge passes | agreement | κ |
   |---|---|---|---|
   | none (v1) | 11 | 20/30 | 0.19 |
   | fail on `conversation_flow` ≤ 2 | 7 | 24/30 | 0.38 |
   | fail on `intent_miss`/`loop`/`interruption_handling` | 7 | 24/30 | 0.38 |

   Gating alone stays well below 0.6, because the judge did not detect the problem in the first place. So
   **the prompt has to change, not only the pass rule.**

### Proposed `rubric-2026-10-v2` + `judge_v2.j2` (not applied)

Dimension keys and weights stay the same, so the API and DB contracts (dimension keys, `ReviewCreate`,
`JudgeOutput`) do not change.

- **Responsiveness, in `task_completion` and `conversation_flow`:**
  - `task_completion`: 4 requires the end state **and** every caller question or request answered or
    explicitly acknowledged ("I don't have that information" counts). **2**: one caller question or request
    never answered. **1**: two or more never answered, or the agent asked again for something the caller had
    already given (a payment date, "already paid").
  - `conversation_flow`: **2**: repeated the same script line once after the caller had answered or objected,
    or ignored one interruption. **1**: repeated it two or more times, or kept talking over the caller.
    **0**: the agent stopped responding (mute) or the call never ended.
- **Escalation:**
  - **2**: a request for a human not honoured by the agent's next turn ("transferred late").
  - **2**: transferred after the caller explicitly declined a human (the needless transfer the description
    already names).
  - **1**: ignored a human request twice. **0** (critical): ignored it three or more times.
- **Empathy:** **1**: repeated the same script to a caller who is visibly frustrated or refusing.
- **Pass gate** (`evaluation/scoring.py`, rubric v2): a call cannot pass with any dimension ≤ 1, or with
  `intent_miss` or `loop` among its failure types. Both are existing enum values.
- **Critical additions:**
  - the agent stopped responding for the rest of the call;
  - it ignored the same caller question or request three or more times.

  Whether non-responsiveness below that level is critical is the owner's call. It is not added here, because
  the owner's critical labels also include calls the rubric would never mark critical (L06, L07, L10).
- **`judge_v2.j2` prompt changes:**
  - **Responsiveness check.** "For every caller turn that asks a question, makes a request, or states a fact
    relevant to the call (already paid, a promised date, a dispute, wanting or refusing a human), check that
    the agent's next turn answers or acknowledges it. List unanswered turns as evidence under
    task_completion and conversation_flow, and add `intent_miss`."
  - **Facts on file.** Rename "Facts the caller knows" to "Facts on file (the only facts the agent may
    state)".
  - **Transfers.** Add: "a transfer the caller declined is not a correct transfer".
- **Owner decisions needed before v2:**
  - `amount_confirmed` as must-pass (L18, L26);
  - the owner's critical definition (L06, L07, L10).

### Calls where the mock agent went mute (not judge issues)

L25 and L27 ("was not speaking at all") are two of **5 `agent_silent` calls: L01, L03, L09, L25, L27.**
- **All 5 used `pstn_office_babble_15db`** (5 of the 8 babble calls). None of the 22 calls on `pstn_8k_alaw`
  or `clean_16k` went mute.
- **They were not provider failures.** During L25 the clean mock agent logged no Gnani errors and made **no
  STT request at all** for the caller's turn (its STT counter stayed at 4). Its VAD never closed the
  utterance under the steady babble noise.
- **Same mechanism as ISSUE-1, at 15 dB.** The street-noise profile (ISSUE-1) did the same at 10 dB.
- **L27 not confirmed from logs.** L27 ran on the `ignore_interrupt` container, whose logs were removed with
  it. Its turns show the same pattern.
- **Effect on the measurement.** Judge and owner both fail all 5, so they slightly *raise* agreement. Without
  them, κ = 0.138 on n = 25.
- **Before a v2 re-run:** fix the mock agent's VAD (ISSUE-1, now including babble), or exclude
  `pstn_office_babble_15db` from calibration batches.

### Overfitting, and a held-out check

- **The risk.** All 30 labels were used to find these problems. Re-scoring the same 30 with v2 would mostly
  confirm that v2 was written to agree with them, so it cannot show that v2 generalises. Thirty calls (5
  owner passes) is also a small base: the κ CI is about 0.65 wide.
- **Held-out check before adopting v2:**
  1. Write v2 from this analysis, as a separate task.
  2. Run a **new** batch with a new seed: about 30 calls, with personas and scenarios not used here, and
     noise profiles that do not mute the mock agent. This costs about $0.3 of DeepSeek plus Gnani time.
  3. The owner labels that batch blind, before seeing any v2 output.
  4. Evaluate it with v1 and v2. Adopt v2 only if κ ≥ 0.6 on the **held-out** batch and v2 does not lose
     agreement on the original 30.
  5. Keep 10 labelled transcripts from both batches as golden tests in `tests/judge/` (§10.4).
