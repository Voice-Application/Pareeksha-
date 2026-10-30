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
  # no authenticated gh: a public repo answers the unauthenticated REST API, whose `private` field gives visibility
  slug=$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
  priv=$(curl -fsS "https://api.github.com/repos/$slug" 2>/dev/null | $PY -c "import json,sys; print(json.load(sys.stdin)['private'])" 2>/dev/null || true)
  case $priv in False) vis=PUBLIC ;; True) vis=PRIVATE ;; *) pending+=("repo visibility could not be read (gh unauthenticated and the REST API gave no answer)") ;; esac
fi
note "repo visibility: $vis"
if [ "$vis" = unknown ]; then pending+=("repo visibility could not be read"); elif [ "$vis" != PUBLIC ]; then problems+=("repo visibility is $vis, not PUBLIC"); fi
# the tag must exist on the remote (a local-only tag does not count as released)
if [ -n "$(git ls-remote --tags origin v1.0.0 2>/dev/null)" ]; then note "tag v1.0.0 on origin: $(git ls-remote --tags origin v1.0.0 | head -1 | cut -c1-12)"
else problems+=("tag v1.0.0 does not exist on origin"); fi
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
GITLEAKS_VERSION=8.30.0
GL=$(command -v gitleaks || true)
if [ -z "$GL" ] && [ "$(uname -s)-$(uname -m)" = Linux-x86_64 ]; then
  # pinned release binary, checked against the checksums file published with the release
  gdir="$ROOT/.tools/gitleaks-$GITLEAKS_VERSION"; mkdir -p "$gdir"
  if [ ! -x "$gdir/gitleaks" ]; then
    base="https://github.com/gitleaks/gitleaks/releases/download/v$GITLEAKS_VERSION"
    tgz="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
    if curl -fsSL -o "$gdir/$tgz" "$base/$tgz" && curl -fsSL -o "$gdir/checksums.txt" "$base/gitleaks_${GITLEAKS_VERSION}_checksums.txt" \
       && (cd "$gdir" && grep " $tgz\$" checksums.txt | sha256sum -c - >/dev/null 2>&1) && tar -xzf "$gdir/$tgz" -C "$gdir" gitleaks; then :; else rm -f "$gdir/gitleaks"; fi
  fi
  [ -x "$gdir/gitleaks" ] && GL="$gdir/gitleaks"
fi
if [ -n "$GL" ]; then
  if "$GL" detect --no-banner --redact --report-format json --report-path "$OUT/V11.gitleaks.json" >"$OUT/V11.gitleaks.log" 2>&1; then
    note "gitleaks $($GL version 2>/dev/null): clean over the full git history"
  else problems+=("gitleaks found secrets (see proof/verify/V11.gitleaks.json, values redacted)"); fi
elif command -v docker >/dev/null && docker run --rm -v "$ROOT:/repo" "zricethezav/gitleaks:v$GITLEAKS_VERSION" detect --source /repo --no-banner --redact >"$OUT/V11.gitleaks.log" 2>&1; then
  note "gitleaks (docker image v$GITLEAKS_VERSION): clean over the full git history"
else
  pending+=("gitleaks not installed and could not be downloaded or run via docker")
fi
[ ${#problems[@]} -gt 0 ] && printf '%s\n' "${problems[@]}" | block
[ ${#pending[@]} -gt 0 ] && { note "Pending inputs:"; printf '%s\n' "${pending[@]}" | block; }
[ ${#problems[@]} -gt 0 ] && finish FAIL "${problems[0]} (+$((${#problems[@]}-1)) more)"
[ ${#pending[@]} -gt 0 ] && finish PENDING "${pending[0]}"
finish PASS "repo public, v1.0.0 tagged, links live, gitleaks clean"
