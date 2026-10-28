#!/bin/sh
# FIX-01(d): bug 2 x2 and clean x2 on the same scenario/persona as QA-03 (sequential: one Gnani request per key).
q="python3 proof/FIX-01/qa03.py run"
P="Promise to pay on Friday"; N=pstn_8k_alaw
$q bug2-no_amount_confirm "EMI Reminder Bot [bug:no_amount_confirm]" "$P" "Priya — careful" $N 2
$q clean-a "EMI Reminder Bot" "$P" "Priya — careful" $N 2
