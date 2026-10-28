#!/usr/bin/env bash
# V1: every task ID in docs/AGENTS.md section 7 has proof/<ID>/proof.md and a verified.md carrying a date and a
# SHA that is an ancestor of HEAD; plus the build-fail grep (TEST_PLAN section 4).
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 1 "Every section-7 task has proof and a signed verified.md"

ids=$(awk '/^## 7\./{on=1;next} /^## /{on=0} on' docs/AGENTS.md | grep -oE '^- \*\*[A-Z]+-[0-9]+[a-z]?\*\*' | sed -E 's/^- \*\*//; s/\*\*$//' | sort -u)
missing=(); total=0
for id in $ids; do
  total=$((total+1)); d=proof/$id
  if [ ! -f $d/proof.md ]; then missing+=("$id: no proof.md"); continue; fi
  if [ ! -f $d/verified.md ]; then missing+=("$id: no verified.md"); continue; fi
  date_ok=$(grep -Eo '20[0-9]{2}-[0-9]{2}-[0-9]{2}' $d/verified.md | head -1)
  sha_ok=""
  for sha in $(grep -Eo '\b[0-9a-f]{7,40}\b' $d/verified.md | sort -u); do
    if git cat-file -e "$sha^{commit}" 2>/dev/null && git merge-base --is-ancestor "$sha" HEAD 2>/dev/null; then sha_ok=$sha; break; fi
  done
  [ -n "$date_ok" ] && [ -n "$sha_ok" ] || missing+=("$id: verified.md lacks a date or a SHA that is an ancestor of HEAD")
done
note "Tasks in AGENTS.md section 7: $total; with complete proof + verified.md: $((total-${#missing[@]}))"
if [ ${#missing[@]} -gt 0 ]; then note; note "Problems:"; printf '%s\n' "${missing[@]}" | block; fi

# Build-fail grep: code outside tests/ and examples/ (tracked files only). Hard patterns fail V1. Line-level
# suppressions that name one rule (# type: ignore[code], # noqa: CODE, eslint-disable-next-line) are listed for
# review but do not fail; file-wide disables (ts-nocheck, bare # type: ignore, eslint-disable without -next-line) do.
paths=(backend/pareeksha mock_agent sdk/python/src action web/app web/components web/lib ':!web/lib/api/schema.d.ts')
hard='STUB\(|TODO|FIXME|NotImplementedError|pass  # placeholder|pytest\.mark\.(skip|xfail)|@ts-nocheck|@ts-ignore|# *type: *ignore *$|eslint-disable($|[^-])'
hits=$(git grep -nE "$hard" -- "${paths[@]}" 2>/dev/null | grep -v '/tests/' || true)
soft=$(git grep -nE '# *type: *ignore\[|# *noqa: *[A-Z]|eslint-disable-next-line' -- "${paths[@]}" 2>/dev/null | grep -v '/tests/' || true)
n=$(printf '%s' "$hits" | grep -c . || true)
ns=$(printf '%s' "$soft" | grep -c . || true)
note; note "Build-fail grep outside tests/ and examples/: $n failing hit(s); $ns single-rule suppression(s) listed for review"
[ "$n" -gt 0 ] && { note "Failing hits:"; printf '%s\n' "$hits" | head -40 | block; }
[ "$ns" -gt 0 ] && { note "Single-rule suppressions (not failing):"; printf '%s\n' "$soft" | head -40 | block; }

if [ ${#missing[@]} -gt 0 ] || [ "$n" -gt 0 ]; then
  finish FAIL "${#missing[@]} task(s) without signed proof, $n build-fail grep hit(s)"
fi
finish PASS "all $total tasks have proof + signed verified.md; build-fail grep clean"
