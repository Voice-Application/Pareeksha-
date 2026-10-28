"""One minimal real TTS -> STT round trip per vendor through pareeksha.speech (VOICE-07 live part).

Needs ELEVENLABS_API_KEY and/or DEEPGRAM_API_KEY; a vendor without a key is skipped. English text (Deepgram Aura
voices are English). Writes <out>/<vendor>_roundtrip.{json,wav}.   python scripts/smoke_speech_live.py proof/VOICE-07/live
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pareeksha.speech import get_stt_provider, get_tts_provider
from pareeksha.speech.base import SpeechProviderName

TEXT = "Hello, this is a short test call about your loan reminder."
LANGUAGE = "en-IN"


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


async def roundtrip(name: SpeechProviderName, key_env: str, out: Path) -> dict[str, object]:
    if not os.environ.get(key_env):
        return {"provider": name.value, "skipped": f"{key_env} not set"}
    tts, stt = get_tts_provider(name), get_stt_provider(name)
    try:
        voices = await tts.list_voices(LANGUAGE)  # the vendors' own list; the first voice is enough
        speech = await tts.synthesize(TEXT, voices[0].id if voices else None, LANGUAGE, sample_rate=16000)
        (out / f"{name.value}_roundtrip.wav").write_bytes(speech.audio)
        transcript = await stt.transcribe(speech.audio, LANGUAGE)
    finally:
        await tts.aclose()
        await stt.aclose()
    ref, hyp = words(TEXT), words(transcript.text)
    report = {
        "provider": name.value,
        "tts": {"voice": speech.voice, "sample_rate": speech.sample_rate,
                "duration_s": speech.duration_s, "usage": speech.usage.model_dump()},
        "stt": {"text": transcript.text, "model": transcript.model, "usage": transcript.usage.model_dump()},
        "reference": TEXT,
        "reference_words_found": f"{sum(w in hyp for w in ref)}/{len(ref)}",
    }
    (out / f"{name.value}_roundtrip.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


async def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, key in ((SpeechProviderName.ELEVENLABS, "ELEVENLABS_API_KEY"),
                      (SpeechProviderName.DEEPGRAM, "DEEPGRAM_API_KEY")):
        print(json.dumps(await roundtrip(name, key, out), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "proof/VOICE-07/live")))
