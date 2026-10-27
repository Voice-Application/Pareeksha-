#!/bin/sh
# FIX-02 clean check (bugs off): every seed scenario x 1 persona, then 4 more personas on one scenario.
# Needs the stack + PAREEKSHA_API_URL / PAREEKSHA_API_KEY in env. Sequential: Gnani allows one request at a time.
q="/tmp/v/bin/python proof/FIX-02/qa03.py run"
S="Already paid, wants confirmation;Promise to pay on Friday;Disputes the EMI amount;Asks for a human;Confused about the due date;Prompt-injection attempt;Abusive caller;Caller goes silent"
$q clean-scenarios "EMI Reminder Bot" "$S" "Priya — careful" pstn_8k_alaw 1
$q clean-personas "EMI Reminder Bot" "Promise to pay on Friday" "The Interrupter;Off-topic tester;Manju — auto driver;Rohit — millennial" pstn_8k_alaw 1
