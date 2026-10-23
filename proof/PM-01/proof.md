# PM-01 proof

Built: `docs/SCOPE.md` with the Must/Should/Could/Won't list copied from PRD §7 (no priority changed), scope notes, and acceptance criteria for all 43 tasks in AGENTS §7, each citing FR/NFR/PRD §8 IDs.

Reproduce (run from repo root):
    grep -oE "^- \*\*[A-Z]+-[0-9]+\*\*" docs/AGENTS.md | grep -oE "[A-Z]+-[0-9]+" | while read id; do grep -q "^- \*\*$id\*\*:" docs/SCOPE.md || echo MISSING $id; done
Expected: no output. Also `grep -c "^- \*\*[A-Z]*-[0-9]*\*\*:" docs/SCOPE.md` prints 43 (see coverage.txt).
Feature check: F1..F30 in PRD §7 vs SCOPE §1: `diff <(grep -oE "^\| F[0-9]+" docs/01-PRD.md | tr -d '| ' | sort -u) <(grep -oE "F[0-9]+" docs/SCOPE.md | sort -u)` expected empty.
Commit: see report.
