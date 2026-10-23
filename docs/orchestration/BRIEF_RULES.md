# Rules for every builder subagent (Pareeksha)

Repo: /home/user/Pareeksha- . Spec in docs/ (start: docs/README.md, docs/AGENTS.md; your row in docs/AGENTS.md §7 defines "done when" and dependencies; §4 working rules; read only the doc sections your task needs).
If your task's dependencies in §7 are not yet done (check STATUS.md), STOP and report STATUS: blocked with the missing dep.

Git: you work in your own worktree/branch `task/<TASK-ID>` created from claude/amazing-einstein-agkccc. Commit there. Do NOT push and do NOT merge into claude/amazing-einstein-agkccc — the orchestrator merges after verification. Commit messages end with:
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0116H9kgtEGmMgngyfExACkx
Do not edit STATUS.md (orchestrator-owned). Append learnings to NOTES.md (1-3 lines + link each).

R1 PROOF: proof/<TASK-ID>/proof.md (what was built, exact commands to reproduce, expected output) + real output (logs, test reports, JSON, screenshots, audio) + commit SHA.
R2 NO SELF-VERIFICATION: never mark your task done; never write verified.md.
R3 NOTHING FAKE: outside tests/ and examples/: no STUB(/TODO/FIXME/NotImplementedError, placeholder or hardcoded results, mocked external services in acceptance runs, skipped tests, disabled lint/type checks, secrets or real personal data. Temporary stubs only as `# STUB(<TASK-ID>)` and list them in your report.
R4 NO GUESSING: on an unknown (vendor API, library error, config) search the web / read official docs or installed package source first; record findings in NOTES.md. Still stuck after two attempts → report blocked with evidence.
R5 CONTRACTS: frozen after TL-01; don't change them; if you need a change, report it as an ISSUE.
R6 HONEST STATUS: report unfinishable work as blocked/failed with reason.
R7 SAFETY: secrets only from .env (never commit .env); synthetic fixtures only; no consent-less voices.
If a needed external key (Gnani/Gemini) is missing from .env, build and unit-test against the documented interface, mark acceptance parts needing the key as blocked on H-01 in proof.md; do not fake outputs.

FINAL REPORT (max 10 lines, no pasted code/logs/diffs):
TASK: <ID> | STATUS: done-unverified / blocked / failed
CHANGED: <files or modules, one line>
COMMIT: <sha> BRANCH: task/<ID>   PROOF: proof/<ID>/
TESTS: <passed/failed counts>
ISSUES: <one line each, max 3>

COST DISCIPLINE (owner budget: $60 total cloud credit, set 2026-10-23):
- Read only the doc sections named in your brief; don't explore the repo beyond the files you own and their direct imports.
- No web research unless blocked; keep it to official docs, 1-2 pages.
- Run the test suite once at the end (plus targeted tests while developing); no repeated full Docker rebuilds.
- Verification is batched by the orchestrator at milestones; just leave a complete proof.md.
