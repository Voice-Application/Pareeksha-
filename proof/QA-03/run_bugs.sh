#!/bin/sh
# 5 planted-bug runs (2 calls each) + clean baselines, sequentially (Gnani: one active request per key).
q="python3 proof/QA-03/qa03.py run"
P="Promise to pay on Friday"; I="Prompt-injection attempt"; N=pstn_8k_alaw
$q bug1-no_disclosure "EMI Reminder Bot [bug:no_disclosure]" "$P" "Priya — careful" $N 2
$q bug2-no_amount_confirm "EMI Reminder Bot [bug:no_amount_confirm]" "$P" "Priya — careful" $N 2
$q bug3-english_to_kannada "EMI Reminder Bot [bug:english_to_kannada]" "$P" "Deepa — homemaker" $N 2
$q bug4-ignore_interrupt "EMI Reminder Bot [bug:ignore_interrupt]" "$P" "The Interrupter" $N 2
$q bug5-false_waiver "EMI Reminder Bot [bug:false_waiver]" "$I" "Off-topic tester" $N 2
$q clean-b "EMI Reminder Bot" "$P" "The Interrupter" $N 2
$q clean-c "EMI Reminder Bot" "$I" "Off-topic tester" $N 2
