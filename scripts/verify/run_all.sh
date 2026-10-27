#!/usr/bin/env bash
# make verify: run V1..V11 (or only the ones given), write proof/FINAL_REPORT.md, exit 1 unless all PASS.
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
steps=("$@"); [ ${#steps[@]} -gt 0 ] || steps=(1 2 3 4 5 6 7 8 9 10 11)

declare -A RESULT
fail=0
for n in "${steps[@]}"; do
  echo "== V$n: ${TITLE[$n]}"
  scripts/verify/${SCRIPT[$n]} | tail -3
  rc=${PIPESTATUS[0]}
  case $rc in 0) RESULT[$n]=PASS ;; 2) RESULT[$n]=PENDING; fail=1 ;; *) RESULT[$n]=FAIL; fail=1 ;; esac
done

{
  echo "# Pareeksha final report"
  echo
  echo "Generated $(date -u +%FT%TZ) by \`make verify\` on commit $(git rev-parse HEAD)."
  echo "PASS only when the evidence file shows the check ran and met its criterion. FAIL = ran and missed (or could not run)."
  echo "PENDING = needs an input only the owner can provide (HubSpot token, labelled calls, demo video, public repo...); it is not a pass."
  echo
  echo "| # | GOAL item | Result | Evidence |"
  echo "|---|---|---|---|"
  for n in "${steps[@]}"; do
    echo "| $n | ${TITLE[$n]} | **${RESULT[$n]}** | [proof/verify/V$n.md](verify/V$n.md) |"
  done
  echo
  for n in "${steps[@]}"; do
    echo "## V$n: ${TITLE[$n]}: ${RESULT[$n]}"
    echo
    sed -n '/^STATUS:/,$p' "proof/verify/V$n.md" 2>/dev/null
    echo
  done
  echo "Sign-off needs every row PASS and Preetham approving the live demo in writing."
} > proof/FINAL_REPORT.md
echo; grep -E '^\| [0-9]+ ' proof/FINAL_REPORT.md
exit $fail
