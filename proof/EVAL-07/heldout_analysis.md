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
