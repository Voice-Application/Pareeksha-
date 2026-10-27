#!/bin/sh
# Second pass after the language-evidence fix: bug 3 re-run (+ paired clean Deepa) and bug 2 on the
# scenario whose must_say is "confirm the amount back to the caller" (+ paired clean).
q="python3 proof/QA-03/qa03.py run"
N=pstn_8k_alaw; P="Promise to pay on Friday"; A="Already paid, wants confirmation"
$q bug3b-english_to_kannada "EMI Reminder Bot [bug:english_to_kannada]" "$P" "Deepa — homemaker" $N 2
$q clean-d "EMI Reminder Bot" "$P" "Deepa — homemaker" $N 2
$q bug2b-no_amount_confirm "EMI Reminder Bot [bug:no_amount_confirm]" "$A" "Priya — careful" $N 2
$q clean-e "EMI Reminder Bot" "$A" "Priya — careful" $N 2
