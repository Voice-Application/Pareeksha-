#!/usr/bin/env bash
# make verify: run V1..V11 (or only the ones given), exit 1 unless every step run here passes. --report-only runs none.
# proof/FINAL_REPORT.md always lists every step, read from its evidence file, so a partial run cannot drop a row.
set -uo pipefail
cd "$(dirname "$0")/../.."
source scripts/verify/lib.sh

declare -A SCRIPT=(
  [1]=v01_proofs.sh [2]=step2_demo_timed.sh [3]=v03_kafka_run.sh [4]=v04_planted_bugs.sh
  [5]=v05_webhook_hubspot.sh [6]=v06_duplicates.sh [7]=v07_dialect.sh [8]=step8_github_action.sh
  [9]=v09_calibration.sh [10]=v10_adopter_guides.sh [11]=v11_release.sh
)
declare -A TITLE=(
  [1]="Every section-7 task has proof and a signed verified.md"
  [2]="compose up + make demo gives an evaluated call in < 20 min"
  [3]="40-call Kafka run, >= 95% free of infra errors; 20-call concurrency-4 timing"
  [4]=">= 4 of 5 planted bugs caught with cited turn indices"
  [5]="Webhook-imported real recording audited, HubSpot note within 3 min"
  [6]="Duplicate delivery and worker crash give one evaluation and one CRM note"
  [7]="Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs"
  [8]="GitHub Action fails a PR enabling a mock bug, passes after the fix"
  [9]="Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6"
  [10]="8 adopter guides followed from a clean clone"
  [11]="Repo public, tagged v1.0.0, demo video + launch post published"
)
report_only=0; if [ "${1:-}" = --report-only ]; then report_only=1; shift; fi
steps=("$@"); [ ${#steps[@]} -gt 0 ] || [ $report_only = 1 ] || steps=(1 2 3 4 5 6 7 8 9 10 11)

fail=0
for n in "${steps[@]}"; do
  echo "== V$n: ${TITLE[$n]}"
  rm -f "proof/verify/V$n.md"  # a step that dies before begin() must not leave its old result standing
  scripts/verify/${SCRIPT[$n]} | tail -3
  [ "${PIPESTATUS[0]}" -eq 0 ] || fail=1
done

evidence() { tr -d '\r' < "proof/verify/V$1.md"; }
status() {  # a step that died before finish() left no STATUS line: it could not run, so FAIL
  [ -f "proof/verify/V$1.md" ] || { echo "NOT RUN"; return; }
  local s; s=$(evidence "$1" | sed -n 's/^STATUS: //p' | tail -1); echo "${s:-FAIL}"
}
head=$(git rev-parse --short HEAD)
last_run() {
  [ -f "proof/verify/V$1.md" ] || { echo "no evidence file"; return; }
  local at sha; read -r at sha < <(evidence "$1" | sed -n 's/^Run at \(.*\) on commit \(.*\)$/\1 \2/p' | head -1)
  if [ "$sha" != "$head" ]; then echo "not re-run; last run $at on $sha"
  elif evidence "$1" | grep -q '^REASON:.*not re-run here'; then echo "$at on this commit: recorded evidence re-checked, not re-run"
  else echo "$at, re-run on this commit"; fi
}

{
  echo "# Pareeksha final report"
  echo
  echo "Generated $(date -u +%FT%TZ) by \`scripts/verify/run_all.sh\` on commit $(git rev-parse HEAD)."
  echo "Each row is read from its evidence file; \"Last run\" says whether that step ran on this commit or an earlier one."
  echo "PASS only when the evidence file shows the check ran and met its criterion. FAIL = ran and missed (or could not run)."
  echo "PENDING = needs an input only the owner can provide (HubSpot token, labelled calls, demo video, public repo...); it is not a pass."
  echo "NOT RUN = no evidence file; it is not a pass."
  echo
  echo "| # | GOAL item | Result | Last run | Evidence |"
  echo "|---|---|---|---|---|"
  for n in 1 2 3 4 5 6 7 8 9 10 11; do
    link="[proof/verify/V$n.md](verify/V$n.md)"; [ -f "proof/verify/V$n.md" ] || link="none"
    echo "| $n | ${TITLE[$n]} | **$(status "$n")** | $(last_run "$n") | $link |"
  done
  echo
  for n in 1 2 3 4 5 6 7 8 9 10 11; do
    echo "## V$n: ${TITLE[$n]}: $(status "$n")"
    echo
    if [ -f "proof/verify/V$n.md" ]; then evidence "$n" | sed -n '/^STATUS:/,$p'; else echo "No proof/verify/V$n.md: this step has no evidence from the harness."; fi
    echo
  done
  [ -f proof/verify/REPORT_NOTES.md ] && { tr -d '\r' < proof/verify/REPORT_NOTES.md; echo; }
  echo "Sign-off needs every row PASS and Preetham approving the live demo in writing."
} > proof/FINAL_REPORT.md
echo; grep -E '^\| [0-9]+ ' proof/FINAL_REPORT.md
exit $fail
