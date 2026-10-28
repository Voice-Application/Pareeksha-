# QA-03: VERIFIED (independent, qa/RC2)

Date 2026-10-27. Tree verified: 9b1ffbc (origin/task/FIX-02), fresh clone, fresh venv. Verifier built nothing. Supersedes proof/QA-03/rejected.md (kept in git history).

Live, one request at a time (Gnani one concurrent): 3 clean scenarios (Promise to pay on Friday, Asks for a human, Disputes the EMI amount; Priya, pstn_8k_alaw): all evaluated, **100/100/100, pass rate 100%, 0 critical** (proof/QA-RC2-ui/qa2-clean.json, run 5cd79283). `make verify` V4 (twice, bugs on/off): caught **5/5** with cited turns, control pass 2/2 then 1/2 (proof/verify/V4.md, V4.catch_report.json; the second run's control was 1 of 2, a variance note: the clean pass rate is high but not deterministic). FIX-02's catch_report.json (5/5, cited turns 0 / 4 / 0,2,4,6 / 2,6,12,14 / 3,5,7,9,14,16) and clean results (7/7 + silent rerun + 4/4 personas) are consistent with what I observed. Not re-spent: the full 8-scenario matrix.
