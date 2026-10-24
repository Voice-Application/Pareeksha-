"""WAV helpers shared by the adapters."""

from __future__ import annotations

import io
import wave


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap 16-bit mono little-endian PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_info(data: bytes) -> tuple[int, float]:
    """Return ``(sample_rate, duration_s)`` of a well-formed WAV."""
    with wave.open(io.BytesIO(data)) as w:
        return w.getframerate(), w.getnframes() / w.getframerate()
