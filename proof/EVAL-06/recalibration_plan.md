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
