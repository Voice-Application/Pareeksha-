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
    """Return ``(sample_rate, duration_s)`` of a WAV.

    Streamed WAVs (Deepgram TTS) carry a placeholder data size in the header, so the frame count is
    capped by the bytes actually present.
    """
    with wave.open(io.BytesIO(data)) as w:
        present = max(len(data) - 44, 0) // (w.getnchannels() * w.getsampwidth())
        return w.getframerate(), min(w.getnframes(), present) / w.getframerate()
