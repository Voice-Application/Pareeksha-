"""PII masking applied to transcripts before any text reaches the judge.

Masks: email, card-like numbers (Luhn valid, 13-19 digits), Aadhaar-like (12 digits),
Indian mobile numbers (10 digits starting 6-9, optional +91/91/0), PAN-like
(`AAAAA9999A`), and spoken digit strings (10+ consecutive digit words in
English / Hindi / Kannada, e.g. "nine eight seven six ...").

Detection runs on an ASCII-digit copy (Devanagari / Kannada digits are mapped 1:1, so
offsets are preserved) and replacements are applied to the original text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .numbers import _LEX, UNIT, _norm_word, to_ascii_digits

PLACEHOLDERS = {
    "email": "[EMAIL]",
    "card": "[CARD]",
    "aadhaar": "[AADHAAR]",
    "phone": "[PHONE]",
    "pan": "[PAN]",
    "spoken_digits": "[DIGITS]",
}


@dataclass(frozen=True)
class PiiFinding:
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class MaskResult:
    text: str
    findings: tuple[PiiFinding, ...]

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.kind] = out.get(f.kind, 0) + 1
        return out


_SEP = r"[ \-\.]?"
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_CARD = re.compile(r"(?<![\d])(?:\d[ \-]?){12,18}\d(?![\d])")
_AADHAAR = re.compile(rf"(?<!\d)\d{{4}}{_SEP}\d{{4}}{_SEP}\d{{4}}(?!\d)")
_PHONE = re.compile(
    rf"(?<![\d\w])(?:(?:\+|00)?91[ \-]?|0)?[6-9]\d{{4}}{_SEP}\d{{5}}(?!\d)"
    rf"|(?<![\d\w])(?:(?:\+|00)?91[ \-]?|0)?[6-9]\d{{2}}{_SEP}\d{{3}}{_SEP}\d{{4}}(?!\d)"
)
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{5}\d{4}[A-Za-z](?![A-Za-z0-9])")

_DIGIT_WORDS = {w for w, (k, v) in _LEX.items() if k == UNIT and v < 10} - {"one", "do"}
_DIGIT_WORDS |= {"oh", "zero", "one", "do"}  # spoken digit strings do use these
_WORD = re.compile(r"\S+")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _spoken_digit_spans(text: str, min_run: int = 10) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    run: list[re.Match[str]] = []

    def flush() -> None:
        if len(run) >= min_run:
            spans.append((run[0].start(), run[-1].end()))
        run.clear()

    for m in _WORD.finditer(text):
        w = _norm_word(m.group(0).strip(".,;:!?()\"'।"))
        if w in _DIGIT_WORDS or (len(w) == 1 and w.isdigit()):
            run.append(m)
        else:
            flush()
    flush()
    return spans


def find_pii(text: str) -> list[PiiFinding]:
    src = to_ascii_digits(text)
    candidates: list[PiiFinding] = []

    def add(kind: str, m: re.Match[str]) -> None:
        candidates.append(PiiFinding(kind, m.start(), m.end()))

    for m in _EMAIL.finditer(src):
        add("email", m)
    for m in _CARD.finditer(src):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            add("card", m)
    for m in _PHONE.finditer(src):
        add("phone", m)
    for m in _AADHAAR.finditer(src):
        add("aadhaar", m)
    for m in _PAN.finditer(src):
        add("pan", m)
    for s, e in _spoken_digit_spans(src):
        candidates.append(PiiFinding("spoken_digits", s, e))

    # Priority: order of kinds above; earlier kinds win overlaps, longer first within a kind.
    order = ["email", "card", "phone", "aadhaar", "pan", "spoken_digits"]
    candidates.sort(key=lambda f: (order.index(f.kind), -(f.end - f.start), f.start))
    kept: list[PiiFinding] = []
    for c in candidates:
        if all(c.end <= k.start or c.start >= k.end for k in kept):
            kept.append(c)
    return sorted(kept, key=lambda f: f.start)


def mask_pii_detailed(text: str) -> MaskResult:
    findings = find_pii(text)
    out, pos = [], 0
    for f in findings:
        out.append(text[pos : f.start])
        out.append(PLACEHOLDERS[f.kind])
        pos = f.end
    out.append(text[pos:])
    return MaskResult("".join(out), tuple(findings))


def mask_pii(text: str) -> str:
    """Return `text` with PII replaced by placeholders such as [PHONE]."""
    return mask_pii_detailed(text).text
