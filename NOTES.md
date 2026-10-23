# NOTES

- EVAL-02: Python `\w` and `str.isalnum` do not match Indic combining vowel signs, so regex word tokenisation splits Kannada/Hindi words; tokenise on whitespace and strip punctuation (backend/pareeksha/evaluation/numbers.py).
- EVAL-02: NFC decomposes Devanagari ज़/ढ़ into base + nukta (U+093C); numeral/WER normalisation strips nukta and maps chandrabindu to anusvara so हज़ार==हजार, पाँच==पांच (numbers.py `_norm_word`).
