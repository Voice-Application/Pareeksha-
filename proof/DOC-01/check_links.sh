#!/usr/bin/env bash
# Verifies relative markdown links in README.md and docs/*.md resolve; checks required files.
set -u
fail=0
for f in README.md docs/*.md; do
  d=$(dirname "$f")
  for l in $(grep -oE '\]\([^)#: ]+\)' "$f" | sed 's/^](//; s/)$//' | sort -u); do
    [ -e "$d/$l" ] || { echo "BROKEN $f -> $l"; fail=1; }
  done
done
for r in README.md STATUS.md CHANGELOG.md NOTES.md docs/README.md docs/AGENTS.md docs/01-PRD.md docs/10-integrations-and-dx.md docs/schema.sql docs/starter/docker-compose.yml; do
  [ -e "$r" ] || { echo "MISSING $r"; fail=1; }
done
[ $fail -eq 0 ] && echo "OK: all links resolve, required files present"
exit $fail
