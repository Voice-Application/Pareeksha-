# V10 (FR-DX-10, NFR-14): proof/DOC-02/guides/<n>.log for the 8 guides of docs/10-integrations-and-dx.md section 7
# (n = 1..8 in the order below). Each log must contain a final "RESULT: PASS" line, written by following the guide
# from a fresh clone. A "RESULT: PENDING" line (needs an owner key) is reported as pending, never as a pass.
cd "$(dirname "$0")/../.." && source scripts/verify/lib.sh
begin 10 "8 adopter guides followed from a clean clone"
guides=(01-quickstart 02-connect-pipecat 03-connect-any-bot 04-webhook-source 05-hubspot 06-github-action 07-write-a-connector 08-operating-kafka)
bad=(); pending=()
for i in "${!guides[@]}"; do
  g=${guides[$i]}; log=proof/DOC-02/guides/$((i+1)).log
  if [ ! -f "$log" ]; then bad+=("$g: no log"); continue; fi
  res=$(grep '^RESULT:' "$log" | tail -1)
  case "$res" in
    "RESULT: PASS"*) note "- $g: ${res:0:120}" ;;
    "RESULT: PENDING"*) pending+=("$g: ${res:0:120}") ;;
    *) bad+=("$g: no passing RESULT line") ;;
  esac
done
note "Guides: ${#guides[@]}; failing: ${#bad[@]}; pending: ${#pending[@]}"
[ ${#bad[@]} -gt 0 ] && printf '%s\n' "${bad[@]}" | block
[ ${#pending[@]} -gt 0 ] && printf '%s\n' "${pending[@]}" | block
[ ${#bad[@]} -gt 0 ] && finish FAIL "${#bad[@]} of ${#guides[@]} guide logs missing or not passing"
[ ${#pending[@]} -gt 0 ] && finish PENDING "${#pending[@]} guide(s) need an owner key"
finish PASS "all 8 guide logs end with RESULT: PASS"
