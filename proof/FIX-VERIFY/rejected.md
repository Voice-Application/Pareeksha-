# FIX-VERIFY rejected (2026-10-30), re-check of allowlist 4fa1fc8 (supersedes earlier text; V6 PASS and V8 PASS still stand)
gitleaks 8.30.0, `--log-opts=HEAD`, clean worktrees. Excerpts: proof/FIX-VERIFY/verifier/gitleaks_4fa1fc8*.txt.
- Fingerprint lines 3f063f4 -> 4fa1fc8: identical (diff of the non-comment lines is empty); 111 entries, all exact `<sha>:<file>:<rule>:<line>`. Only comments changed. PASS.
- Planted AKIA key in a throwaway commit (discarded, never pushed): still reported (1 -> 2). PASS.
- **(3) FAIL: full-history scan at 4fa1fc8 reports 1.** The finding is `3f063f429cabf9854b8fcda759ed69a5e0830921:.gitleaksignore:generic-api-key:28`: the OLD commit 3f063f4 contains the version of .gitleaksignore that quoted the test secret. Rewording in a new commit does not remove it from history.
- **(5) FAIL: 4fa1fc8 merged locally into origin/main 74c5c5c (merge fde86a6, no conflicts) reports the same 1 finding.** No other finding resurfaces.
Fix (builder): add that one exact fingerprint line (`3f063f429cabf9854b8fcda759ed69a5e0830921:.gitleaksignore:generic-api-key:28`, with a reason comment that does not quote the value) to .gitleaksignore, or squash 3f063f4 into 4fa1fc8 before merging; then re-scan to 0. Adding the line creates no new finding, because the ignore file at HEAD is what gitleaks reads.
Still open for the owner: tag v1.0.0, demo video, launch post.
