"""Text helpers shared by the TTS callers and providers."""

from __future__ import annotations

import unicodedata


def has_speakable_text(text: str) -> bool:
    """True when ``text`` has a letter, digit or Indic vowel sign / virama, so a TTS can voice it.

    Punctuation, symbols and whitespace alone ("...", "-", "?!") yield no audio from any provider.
    """
    return any(ch.isalnum() or unicodedata.category(ch).startswith("M") for ch in text)


def is_no_audio_message(message: str) -> bool:
    """True for a provider's "no audio generated" failure, which repeats for the same text."""
    return "no audio generated" in message.lower()
