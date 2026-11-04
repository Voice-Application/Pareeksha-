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
    """Stereo output (agent on the left channel, caller on the right) when argv[2] == "stereo"."""
    stereo = len(sys.argv) > 2 and sys.argv[2] == "stereo"
    tts = get_tts_provider()
    rate = 16000
    chunks: list[tuple[int, bytes]] = []
    for voice, text in TURNS:
        res = await tts.synthesize(text, voice, LANGUAGE, sample_rate=rate)
        with wave.open(io.BytesIO(res.audio)) as w:
            chunks.append((0 if voice == TURNS[0][0] else 1, w.readframes(w.getnframes())))
    gap = b"\x00\x00" * int(rate * 0.6)
    if not stereo:
        pcm = b"".join(c + gap for _, c in chunks)
    else:
        import array
        left, right = array.array("h"), array.array("h")
        for side, c in chunks:
            a = array.array("h", c + gap)
            z = array.array("h", [0]) * len(a)
            (left.extend(a), right.extend(z)) if side == 0 else (left.extend(z), right.extend(a))
        inter = array.array("h", [0]) * (2 * len(left))
        inter[0::2], inter[1::2] = left, right
        pcm = inter.tobytes()
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2 if stereo else 1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(pcm)
    print(f"wrote {out} ({len(pcm) / 2 / rate / (2 if stereo else 1):.1f}s)")


asyncio.run(main(Path(sys.argv[1])))
