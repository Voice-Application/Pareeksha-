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
