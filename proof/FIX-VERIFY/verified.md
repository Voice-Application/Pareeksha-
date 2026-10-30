# FIX-VERIFY verified (2026-10-30, SHA 5aef2db; earlier SHA fdd8953 checks below)
Verifier re-ran from clean worktrees (excerpts in proof/FIX-VERIFY/verifier/).
- V6 (fdd8953) PASS on my own stack: Kafka suite ran pytest, 9 passed (Python 3.12.3); replay x2 + SIGKILL: 1 evaluation, 0 duplicate deliveries, 0 duplicate notes.
- V8 PASS: run 41097075186 failure on a8f8444, then 41102511599 success on b8b121e (descendant). GOAL 8: acceptable but not literal; the passing run was a manual workflow_dispatch (the PR paths filter skipped the pull_request trigger), so it is not a PR check. Same workflow, descendant commit, mechanism shown; owner may accept.
- V11 FAIL until the owner creates tag v1.0.0 (repo public, URL 200); the tag logic is right.
- Allowlist at 5aef2db: the 111 original fingerprint lines are unchanged; the orchestrator's edit adds exactly one more exact fingerprint (3f063f42...:.gitleaksignore:generic-api-key:28, a history finding whose line quoted a dummy test secret), with a reason that does not quote it. All 112 lines are exact `<sha>:<file>:<rule>:<line>`; no path- or rule-wide entries. 21 of the 111 were spot-checked earlier against `git show`: all false positives.
- Full-history gitleaks 8.30.0 at 5aef2db: "no leaks found". After a local merge into origin/main 74c5c5c (merge ccd217a, no qa/ commits): "no leaks found". A planted AKIA key in a throwaway commit (discarded, never pushed) is still reported.
- Bookkeeping proofs ALL-01, H-01, DOC-03, PJM-01 verified separately (their verified.md); owner parts not done: demo recording, tag v1.0.0, demo video link, launch post.
- Caveat: qa/FIX-VERIFY's own gitleaks_report.json contains fingerprint strings and is flagged by a scan that includes this branch; do not merge this branch into the release.
