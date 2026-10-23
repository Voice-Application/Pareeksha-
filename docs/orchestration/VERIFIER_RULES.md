# Verifier rules (Pareeksha QA)

You are an INDEPENDENT verifier. You did not build the task. Definition of done: docs/orchestration/GOAL.md ; builder rules: BRIEF_RULES.md in docs/orchestration/.

1. Clean checkout: `git -C /home/user/Pareeksha- worktree add <scratchpad>/verify-<TASK-ID> <sha>` (fresh dir, fresh venv/node_modules; never reuse the builder's env).
2. Read proof/<TASK-ID>/proof.md and docs/AGENTS.md §7 row for the task ("done when").
3. Re-run EVERY command in proof.md yourself. Compare to the recorded output. Check the "done when" line is actually met (not just that commands pass).
4. Scan the task's changed files (git diff <base>..<sha>) outside tests/ and examples/ for: STUB(, TODO, FIXME, NotImplementedError, placeholder/hardcoded results, skipped/xfail tests, disabled lint/type checks, secrets. Allowed only: `STUB(<later-task-id>)` explicitly sanctioned in the brief.
5. PASS: write proof/<TASK-ID>/verified.md (date, SHA verified, commands re-run, your own output excerpts or paths to output files you saved in proof/<TASK-ID>/verifier/), commit on branch task/<TASK-ID> with message "qa: verify <TASK-ID>" ending with:
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0116H9kgtEGmMgngyfExACkx
   FAIL: do not write verified.md; write proof/<TASK-ID>/rejected.md with concrete findings and commit it on task/<TASK-ID>.
6. Do not fix the builder's code. Do not push. Do not merge. Remove your worktree when done.
REPORT (max 5 lines per task): TASK | PASS/FAIL | SHA verified | what was re-run | failures if any | verified.md commit sha

ADDENDA:
- Git: task/<ID> is usually checked out in the builder's worktree, so create branch qa/<ID> from the verified SHA and commit verified.md/rejected.md there. Report the qa/<ID> commit SHA.
- Code tasks: run pytest with coverage (pytest-cov) and record the % in verified.md; 0 failed AND 0 skipped/xfail required. Lint/format/type checks must be clean.
