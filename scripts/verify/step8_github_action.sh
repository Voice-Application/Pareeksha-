#!/usr/bin/env bash
# V8 (FR-DX-6, FR-RG-4, FR-DX-4): the Pareeksha Action fails a PR that enables a mock bug and passes after the fix.
# Input: proof/QA-05/action_runs.txt with two lines, "<run url of the failing PR run>" then "<run url after the fix>".
# Needs the GitHub CLI authenticated for the repo; PENDING until the two runs exist (they need repo secrets and a
# reachable Pareeksha instance, see .github/workflows/pareeksha-regression.yml).
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 8 "GitHub Action fails a PR enabling a mock bug, passes after the fix"
f=proof/QA-05/action_runs.txt
if [ ! -s "$f" ]; then
  note "$f is missing: the two Actions runs (PR enabling a mock bug, then the fix) have not been recorded."
  finish PENDING "no recorded Actions run URLs"
fi
command -v gh >/dev/null || finish PENDING "gh CLI not installed here; cannot read the run results"
bad=$(sed -n 1p "$f"); good=$(sed -n 2p "$f")
info() { gh run view "$(basename "$1")" --repo "$(echo "$1" | sed -E 's#https://github.com/([^/]+/[^/]+)/actions/runs/.*#\1#')" --json conclusion,headSha,workflowName 2>/dev/null; }
b=$(info "$bad") || finish FAIL "cannot read $bad"
g=$(info "$good") || finish FAIL "cannot read $good"
{ echo "$b"; echo "$g"; } | block
field() { echo "$1" | $PY -c "import json,sys; print(json.load(sys.stdin)['$2'])"; }
bc=$(field "$b" conclusion); gc=$(field "$g" conclusion)
bw=$(field "$b" workflowName); gw=$(field "$g" workflowName)
bs=$(field "$b" headSha); gs=$(field "$g" headSha)
desc=no; git cat-file -e "$bs^{commit}" 2>/dev/null && git cat-file -e "$gs^{commit}" 2>/dev/null && git merge-base --is-ancestor "$bs" "$gs" && desc=yes
note "first: $bc ($bw @ $bs); second: $gc ($gw @ $gs); second descends from first: $desc"
[ "$bc" = failure ] && [ "$gc" = success ] && [ "$bw" = "$gw" ] && [ "$desc" = yes ] && finish PASS "first run failed, second passed, same workflow, second commit descends"
finish FAIL "expected failure then success of the same workflow on descending commits"
