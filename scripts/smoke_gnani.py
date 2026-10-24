"""Gnani smoke test: kn/hi TTS -> STT round trips, stream STT, batch STT with diarization.

Synthetic speech only (TTS output); no human voices. Reads GNANI_API_KEY from the
environment or .env. Writes WAVs, transcripts and a usage ledger to --out.

    python scripts/smoke_gnani.py --out proof/VOICE-01
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pareeksha.evaluation.metrics import wer
from pareeksha.gnani import GnaniSpeech, wav_duration_s

PHRASES = {
    "kn-IN": "ನಮಸ್ಕಾರ, ನನ್ನ ಇಎಂಐ ಬಾಕಿ ಮೊತ್ತ ಎಷ್ಟು ಎಂದು ದಯವಿಟ್ಟು ತಿಳಿಸಿ.",
    "hi-IN": "नमस्ते, मेरी ईएमआई की बकाया राशि कितनी है, कृपया बताइए।",
}
# two timbre-v3.0 voices per language are auditioned
VOICES = {"kn-IN": ["Lakshmi", "Avinash"], "hi-IN": ["Shivani", "Shubham"]}
AGENT_LINE = {
    "kn-IN": "ನಮಸ್ಕಾರ, ನಿಮ್ಮ ಇಎಂಐ ಬಾಕಿ ಮೊತ್ತ ಎರಡು ಸಾವಿರ ರೂಪಾಯಿ.",
    "hi-IN": "नमस्ते, आपकी ईएमआई की बकाया राशि दो हज़ार रुपये है।",
}


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def pcm_of(wav: bytes) -> bytes:
    with wave.open(io.BytesIO(wav)) as w:
        return w.readframes(w.getnframes())


def join_wavs(parts: list[bytes], rate: int, gap_s: float = 0.8) -> bytes:
    silence = b"\x00" * int(gap_s * rate * 2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(silence.join(pcm_of(p) for p in parts))
    return buf.getvalue()


async def main(out: Path) -> None:
    load_env()
    if not os.environ.get("GNANI_API_KEY"):
        sys.exit("GNANI_API_KEY missing (env or .env)")
    out.mkdir(parents=True, exist_ok=True)
    g = GnaniSpeech(cache_dir=out / "tts_cache")
    report: dict = {"round_trips": [], "stream": [], "batch": {}}

    # 1. TTS -> REST STT round trips, kn + hi, two voices each
    for lang, text in PHRASES.items():
        for voice in VOICES[lang]:
            tts = g.synthesize(text, voice, lang)
            name = f"{lang}_{voice}"
            (out / f"{name}.wav").write_bytes(tts.audio)
            res = g.transcribe(tts.audio, lang)
            hyp = res.get("transcript", "")
            (out / f"{name}.transcript.txt").write_text(hyp, encoding="utf-8")
            row = {
                "lang": lang,
                "voice": voice,
                "tts_seconds": round(tts.seconds, 2),
                "reference": text,
                "hypothesis": hyp,
                "wer": wer(text, hyp),
                "stt_model": res.get("model"),
                "stt_processing_time": res.get("processing_time"),
            }
            report["round_trips"].append(row)
            print(f"[rest] {name} wer={row['wer']} -> {hyp}")

    # 2. streaming STT (Hindi, first voice)
    hi_wav = (out / f"hi-IN_{VOICES['hi-IN'][0]}.wav").read_bytes()
    events = await g.transcribe_stream(pcm_of(hi_wav), "hi-IN")
    for e in events:
        report["stream"].append(
            {"text": e.text, "audio_ms": e.audio_duration_ms, "latency_ms": e.latency}
        )
    joined = " ".join(e.text for e in events)
    report["stream_wer"] = wer(PHRASES["hi-IN"], joined)
    (out / "stream_hi-IN.transcript.txt").write_text(joined, encoding="utf-8")
    print(f"[stream] {len(events)} segments wer={report['stream_wer']} -> {joined}")

    # 3. batch STT with diarization on a synthetic two-speaker call (Kannada)
    caller = g.synthesize(PHRASES["kn-IN"], VOICES["kn-IN"][0], "kn-IN")
    agent = g.synthesize(AGENT_LINE["kn-IN"], VOICES["kn-IN"][1], "kn-IN")
    call = join_wavs([caller.audio, agent.audio], caller.sample_rate)
    (out / "batch_kn-IN_call.wav").write_bytes(call)
    segs = g.transcribe_batch(call, "kn-IN", speakers=2)
    report["batch"] = {
        "duration_s": round(wav_duration_s(call), 2),
        "segments": segs,
        "speakers_seen": sorted(
            {s["speaker"] for s in segs if s["speaker"] is not None}
        ),
        "reference_turns": [PHRASES["kn-IN"], AGENT_LINE["kn-IN"]],
    }
    (out / "batch_kn-IN.transcript.json").write_text(
        json.dumps(segs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[batch] segments={len(segs)} speakers={report['batch']['speakers_seen']}")

    report["usage_totals"] = g.ledger.totals()
    report["usage_records"] = g.ledger.as_dicts()
    (out / "smoke_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["usage_totals"], indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "proof" / "VOICE-01")
    asyncio.run(main(ap.parse_args().out))
