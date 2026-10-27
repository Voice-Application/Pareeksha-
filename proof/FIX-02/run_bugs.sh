#!/bin/sh
# FIX-02: the 5 planted bugs once each (sequential: one Gnani request per key), after start_bug_agents.sh + `qa03.py setup`.
q="/tmp/v/bin/python proof/FIX-02/qa03.py run"
P="Promise to pay on Friday"; I="Prompt-injection attempt"; N=pstn_8k_alaw
$q bug1-no_disclosure "EMI Reminder Bot [bug:no_disclosure]" "$P" "Priya — careful" $N 1
$q bug2-no_amount_confirm "EMI Reminder Bot [bug:no_amount_confirm]" "$P" "Priya — careful" $N 1
$q bug3-english_to_kannada "EMI Reminder Bot [bug:english_to_kannada]" "$P" "Deepa — homemaker" $N 1
$q bug4-ignore_interrupt "EMI Reminder Bot [bug:ignore_interrupt]" "$P" "The Interrupter" $N 1
$q bug5-false_waiver "EMI Reminder Bot [bug:false_waiver]" "$I" "Off-topic tester" $N 1
