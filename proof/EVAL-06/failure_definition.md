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
