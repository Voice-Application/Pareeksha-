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
