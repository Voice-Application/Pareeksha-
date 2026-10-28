"""Build a short synthetic two-speaker call recording (agent + customer) with Gnani TTS (LIVE-ACCEPT).

Sequential TTS calls (Gnani allows one concurrent request); output is mono 16 kHz WAV with a pause
between turns. Needs GNANI_API_KEY.   python scripts/live_make_recording.py out.wav
"""

from __future__ import annotations

import asyncio
import io
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pareeksha.speech import get_tts_provider

LANGUAGE = "hi-IN"
TURNS = [
    ("Shivani", "नमस्ते, मैं टेस्ट बैंक से बोल रही हूँ। आपकी ई एम आई की रकम चार हज़ार रुपये है।"),
    ("Devansh", "जी, मैं इस महीने की दस तारीख तक भुगतान कर दूँगा।"),
    ("Shivani", "धन्यवाद। आपकी तारीख नोट कर ली गई है।"),
]


async def main(out: Path) -> None:
    tts = get_tts_provider()
    pcm = b""
    rate = 16000
    for voice, text in TURNS:
        res = await tts.synthesize(text, voice, LANGUAGE, sample_rate=rate)
        with wave.open(io.BytesIO(res.audio)) as w:
            pcm += w.readframes(w.getnframes()) + b"\x00\x00" * int(rate * 0.6)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(pcm)
    print(f"wrote {out} ({len(pcm) / 2 / rate:.1f}s)")


asyncio.run(main(Path(sys.argv[1])))
