"""ASR text normalisation (FR-DI-3): the same function is applied to reference and hypothesis.

Steps: Unicode NFC; drop zero-width joiners; lower-case; digits of every script to ASCII; spoken
numbers (including lakh / crore and Kannada / Hindi number words) to digits via
``pareeksha.evaluation.numbers``; punctuation removed (letters, combining marks and digits are kept,
so Kannada vowel signs survive); script-variant equivalences (Devanagari nukta and chandrabindu,
Kannada archaic ra / lla); loanwords in any script unified to one canonical Latin token
(``loanwords.yaml``).
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

from pareeksha.evaluation.numbers import normalize_numbers, to_ascii_digits

_LOANWORDS_FILE = Path(__file__).with_name("loanwords.yaml")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
# Devanagari: nukta dropped (ज़ -> ज, ड़ -> ड), chandrabindu -> anusvara. Kannada: archaic letters.
_EQUIVALENT = str.maketrans({"़": None, "ँ": "ं", "ಱ": "ರ", "ೞ": "ಳ"})


@lru_cache(maxsize=1)
def loanword_map() -> dict[str, str]:
    """Spelling (NFC) -> canonical Latin token."""
    raw = yaml.safe_load(_LOANWORDS_FILE.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for canonical, variants in raw.items():
        for variant in variants:
            mapping[_basic(variant)] = str(canonical)
    return mapping


def _basic(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    return unicodedata.normalize("NFC", text.translate(_EQUIVALENT))


def _strip_punctuation(text: str) -> str:
    return "".join(
        ch if unicodedata.category(ch)[0] in "LMN" or ch.isspace() else " " for ch in text
    )


def normalize(text: str) -> str:
    """Normalised, whitespace-collapsed text (empty string when nothing remains)."""
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH).lower()
    text = normalize_numbers(to_ascii_digits(text))
    text = _basic(_strip_punctuation(text))
    loans = loanword_map()
    return " ".join(loans.get(tok, tok) for tok in text.split())
