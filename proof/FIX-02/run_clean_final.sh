#!/bin/sh
# Final clean check on the committed mock agent: 8 seed scenarios x Priya, concurrency 1 (Gnani: one request per key).
S="Already paid, wants confirmation;Promise to pay on Friday;Disputes the EMI amount;Asks for a human;Confused about the due date;Prompt-injection attempt;Abusive caller;Caller goes silent"
/tmp/v/bin/python proof/FIX-02/qa03.py run clean-scenarios-final "EMI Reminder Bot" "$S" "Priya — careful" pstn_8k_alaw 1
