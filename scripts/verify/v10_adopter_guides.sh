#!/usr/bin/env bash
# V10 (FR-DX-10, NFR-14): proof/QA-05/adopter_guides/<guide>.log for the 8 guides of docs/10-integrations-and-dx.md
# section 7; each must end with "GUIDE-RESULT: PASS exit=0". A verifier follows each guide from a clean clone and
# records the log; this step does not fake them.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 10 "8 adopter guides followed from a clean clone"
guides=(01-quickstart 02-connect-pipecat 03-connect-any-bot 04-webhook-source 05-hubspot 06-github-action 07-write-a-connector 08-operating-kafka)
bad=()
for g in "${guides[@]}"; do
  log=proof/QA-05/adopter_guides/$g.log
  if [ ! -f "$log" ]; then bad+=("$g: no log"); continue; fi
  tail -1 "$log" | grep -q '^GUIDE-RESULT: PASS exit=0$' || bad+=("$g: last line is not 'GUIDE-RESULT: PASS exit=0'")
done
note "Guides: ${#guides[@]}; problems: ${#bad[@]}"
[ ${#bad[@]} -gt 0 ] && printf '%s\n' "${bad[@]}" | block
[ ${#bad[@]} -eq 0 ] && finish PASS "all 8 guide logs end with GUIDE-RESULT: PASS exit=0"
finish FAIL "${#bad[@]} of ${#guides[@]} guide logs missing or not passing"
