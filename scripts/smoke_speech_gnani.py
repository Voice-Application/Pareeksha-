"""One real Gnani round trip through the speech provider abstraction (VOICE-07).

TTS (registry default provider) -> STT REST. Spends one TTS call and one STT call. Needs
GNANI_API_KEY in the environment. Writes the WAV and a JSON report into the given directory.

    python scripts/smoke_speech_gnani.py proof/VOICE-07
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pareeksha.speech import get_stt_provider, get_tts_provider, provider_status  # noqa: E402

TEXT = "नमस्ते, आपकी ई एम आई बाकी है।"
LANGUAGE = "hi-IN"
VOICE = "Shivani"


async def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tts, stt = get_tts_provider(), get_stt_provider()  # STT_PROVIDER / TTS_PROVIDER default: gnani
    speech = await tts.synthesize(TEXT, VOICE, LANGUAGE, sample_rate=16000)
    (out / "gnani_adapter_roundtrip.wav").write_bytes(speech.audio)
    transcript = await stt.transcribe(speech.audio, LANGUAGE)
    report = {
        "provider_status": [
            {"name": s.name.value, "configured": s.configured} for s in provider_status()
        ],
        "tts": {
            "voice": speech.voice,
            "chars": len(TEXT),
            "sample_rate": speech.sample_rate,
            "duration_s": speech.duration_s,
            "usage": speech.usage.model_dump(),
        },
        "stt": {
            "text": transcript.text,
            "model": transcript.model,
            "usage": transcript.usage.model_dump(),
        },
        "reference": TEXT,
    }
    (out / "gnani_adapter_roundtrip.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "proof/VOICE-07")))
