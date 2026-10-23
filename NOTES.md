# NOTES

- EVAL-02: Python `\w` and `str.isalnum` do not match Indic combining vowel signs, so regex word tokenisation splits Kannada/Hindi words; tokenise on whitespace and strip punctuation (backend/pareeksha/evaluation/numbers.py).
- EVAL-02: NFC decomposes Devanagari ज़/ढ़ into base + nukta (U+093C); numeral/WER normalisation strips nukta and maps chandrabindu to anusvara so हज़ार==हजार, पाँच==पांच (numbers.py `_norm_word`).
- INFRA-01: apache/kafka:4.0.0 + KRaft compose works unchanged from starter; kafka-init is idempotent. Behind a TLS-intercepting proxy `pip` inside `docker build` fails SSL; use `docker-compose.proxy.yml` (CA as build secret) rather than disabling verification. See proof/INFRA-01/proof.md.
- INFRA-01: worker services need compose profile `workers` until their modules exist (INFRA-02+), else crash-loop. See docker-compose.yml.
