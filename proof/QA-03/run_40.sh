#!/bin/sh
# GOAL item 3: 5 scenarios x 4 personas x 2 noise profiles = 40 calls through Kafka (clean mock agent).
python3 proof/QA-03/qa03.py run run40 "EMI Reminder Bot" \
 "Already paid, wants confirmation;Promise to pay on Friday;Disputes the EMI amount;Asks for a human;Confused about the due date" \
 "Priya — careful;Deepa — homemaker;Mohan — labourer;Imran — shopkeeper" \
 "pstn_8k_alaw;mobile_weak_signal" 1
