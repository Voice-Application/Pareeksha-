#!/usr/bin/env bash
# V8 (FR-DX-6, FR-RG-4, FR-DX-4): the Pareeksha Action fails a PR that enables a mock bug and passes after the fix.
# Input: proof/QA-05/action_runs.txt with two lines, "<run url of the failing PR run>" then "<run url after the fix>".
# Reads each run with the GitHub CLI when it works, else from the unauthenticated REST API (public repo, curl);
# PENDING until the two runs exist (they need repo secrets and a
# reachable Pareeksha instance, see .github/workflows/pareeksha-regression.yml).
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 8 "GitHub Action fails a PR enabling a mock bug, passes after the fix"
f=proof/QA-05/action_runs.txt
if [ ! -s "$f" ]; then
  note "$f is missing: the two Actions runs (PR enabling a mock bug, then the fix) have not been recorded."
  finish PENDING "no recorded Actions run URLs"
fi
bad=$(sed -n 1p "$f"); good=$(sed -n 2p "$f")
info() {
  local url=$1 slug id out
  slug=$(echo "$url" | sed -E 's#https://github.com/([^/]+/[^/]+)/actions/runs/.*#\1#'); id=$(basename "$url")
  if command -v gh >/dev/null && out=$(gh run view "$id" --repo "$slug" --json conclusion,headSha,workflowName 2>/dev/null); then
    echo "$out"; return 0
  fi
  curl -fsS "https://api.github.com/repos/$slug/actions/runs/$id" | $PY -c "
import json, sys
d = json.load(sys.stdin)
print(json.dumps({'conclusion': d['conclusion'], 'headSha': d['head_sha'], 'workflowName': d['name']}))"
}
b=$(info "$bad") || finish FAIL "cannot read $bad"
g=$(info "$good") || finish FAIL "cannot read $good"
{ echo "$b"; echo "$g"; } | block
field() { echo "$1" | $PY -c "import json,sys; print(json.load(sys.stdin)['$2'])"; }
bc=$(field "$b" conclusion); gc=$(field "$g" conclusion)
bw=$(field "$b" workflowName); gw=$(field "$g" workflowName)
bs=$(field "$b" headSha); gs=$(field "$g" headSha)
for sha in "$bs" "$gs"; do git cat-file -e "$sha^{commit}" 2>/dev/null || git fetch -q origin "$sha" >/dev/null 2>&1 || true; done
desc=no; git cat-file -e "$bs^{commit}" 2>/dev/null && git cat-file -e "$gs^{commit}" 2>/dev/null && git merge-base --is-ancestor "$bs" "$gs" && desc=yes
note "first: $bc ($bw @ $bs); second: $gc ($gw @ $gs); second descends from first: $desc"
[ "$bc" = failure ] && [ "$gc" = success ] && [ "$bw" = "$gw" ] && [ "$desc" = yes ] && finish PASS "first run failed, second passed, same workflow, second commit descends"
finish FAIL "expected failure then success of the same workflow on descending commits"
