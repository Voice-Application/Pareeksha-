# FIX-VERIFY rejected (2026-10-30), re-check of allowlist 3f063f4 (supersedes the earlier text; V6 PASS and V8 PASS above still stand)
gitleaks 8.30.0, run with `--log-opts=HEAD` in a clean worktree. Excerpts in proof/FIX-VERIFY/verifier/gitleaks_3f063f4.txt.
1. PASS: 111 entries, 21 spot-checked across all 7 groups with `git show <commit>:<file>`: every one is a UUID/event id, a dummy test secret, `Bearer pk_live_x`, a `$A` curl variable or a plain curl line. Reasons are correct.
2. PASS: every non-comment line matches `<40-hex>:<file>:<rule>:<line>`; no path-wide or rule-wide entries.
3. **FAIL: scan at 3f063f4 reports 1, not 0.** `.gitleaksignore:28` (rule generic-api-key, commit 3f063f4) is a comment that quotes the test secret `SECRET = '0123456789abcdef-signing'`, so the allowlist file itself is a new finding. V11 would still say "gitleaks found secrets". Fix: reword the comment so it does not quote the secret, add that new fingerprint (the commit will change, so re-derive it), and re-scan.
4. PASS: planted `AKIA...` + secret-key lines in a throwaway commit (never pushed, discarded) were reported (1 -> 2 findings).
5. FAIL (same cause): 3f063f4 merged locally into origin/main 74c5c5c merges cleanly and resurfaces nothing old, but the scan still reports the 1 finding at `.gitleaksignore:28`.
Note for the orchestrator: a plain `gitleaks detect` scans all refs. My own report proof/FIX-VERIFY/verifier/gitleaks_report.json (qa/FIX-VERIFY dc6a121) contains the fingerprint strings and is flagged 8 times (curl-auth-user, report lines 571/1159/1726/2314). It lives only on qa/FIX-VERIFY, so do not merge that branch into the release; if it must be kept, I can redact that file's fingerprints.
Still open for the owner: tag v1.0.0, demo video, launch post.
