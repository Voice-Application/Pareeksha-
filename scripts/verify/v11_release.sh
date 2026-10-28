#!/usr/bin/env bash
# V11 (PRD section 8 portfolio): repo PUBLIC, tag v1.0.0, demo video + launch post links in proof/PJM-01/release.md
# return HTTP 200, gitleaks clean. Never makes anything public: it only reads state.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 11 "Repo public, tagged v1.0.0, demo video + launch post published"
problems=(); pending=()
vis=unknown
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  vis=$(gh repo view --json visibility -q .visibility 2>/dev/null || echo unknown)
else
  pending+=("gh CLI not installed/authenticated")
fi
note "repo visibility: $vis"
if [ "$vis" = unknown ]; then pending+=("repo visibility could not be read"); elif [ "$vis" != PUBLIC ]; then problems+=("repo visibility is $vis, not PUBLIC"); fi
git rev-parse -q --verify refs/tags/v1.0.0 >/dev/null || problems+=("tag v1.0.0 does not exist")
rel=proof/PJM-01/release.md
if [ -f "$rel" ]; then
  for u in $(grep -Eo 'https?://[^ )>]+' "$rel" | sort -u); do
    code=$(curl -s -o /dev/null -w '%{http_code}' -L "$u"); note "$u -> $code"
    [ "$code" = 200 ] || problems+=("$u returned $code")
  done
  grep -Eqi 'youtu|loom|vimeo|video' "$rel" || problems+=("release.md has no demo video link")
  grep -Eqi 'launch|post|linkedin|blog' "$rel" || problems+=("release.md has no launch post link")
else
  pending+=("$rel missing: demo video and launch post not recorded")
fi
if command -v gitleaks >/dev/null; then
  gitleaks detect --no-banner >/dev/null 2>&1 && note "gitleaks: clean" || problems+=("gitleaks found secrets")
else
  pending+=("gitleaks not installed")
fi
[ ${#problems[@]} -gt 0 ] && printf '%s\n' "${problems[@]}" | block
[ ${#pending[@]} -gt 0 ] && { note "Pending inputs:"; printf '%s\n' "${pending[@]}" | block; }
[ ${#problems[@]} -gt 0 ] && finish FAIL "${problems[0]} (+$((${#problems[@]}-1)) more)"
[ ${#pending[@]} -gt 0 ] && finish PENDING "${pending[0]}"
finish PASS "repo public, v1.0.0 tagged, links live, gitleaks clean"
