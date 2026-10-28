#!/bin/sh
# Final live checks on the committed mock agent: clean 8 scenarios x Priya, then the 5 planted bugs once each, sequentially.
S="Already paid, wants confirmation;Promise to pay on Friday;Disputes the EMI amount;Asks for a human;Confused about the due date;Prompt-injection attempt;Abusive caller;Caller goes silent"
/tmp/v/bin/python proof/FIX-02/qa03.py run clean-scenarios-final "EMI Reminder Bot" "$S" "Priya — careful" pstn_8k_alaw 1
sh proof/FIX-02/run_bugs.sh
