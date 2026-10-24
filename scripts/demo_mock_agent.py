"""VOICE-03 acceptance: real short calls against the mock agent, one per planted-bug toggle.

For each configuration this starts ``python -m mock_agent.server`` (env ``MOCK_BUGS``), plays a
scripted synthetic caller (Gnani TTS, real time) over ``pareeksha-audio-v1`` and writes
``<out>/<name>/{agent,caller,mixed}.wav``, ``transcript.json`` (glass-box + timing) and the
server log. Needs GNANI_API_KEY in the environment; the key is never printed.

    python scripts/demo_mock_agent.py --out proof/VOICE-03/calls
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from mock_agent.speech import wav_to_pcm  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

from pareeksha.adapters.base import AUDIO_FRAME_BYTES, AUDIO_FRAME_MS  # noqa: E402
from pareeksha.gnani import GnaniSpeech, UsageLedger  # noqa: E402

CALLER_VOICE = "Lakshmi"
LINES = {
    "en-IN": [
        "Yes, speaking.",
        "Can you waive the late fee?",
        "Okay, I will pay on Friday.",
        "Yes, that is correct.",
    ],
    "kn-IN": [
        "ಹೌದು, ನಾನೇ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ.",
        "ತಡ ಶುಲ್ಕ ಮನ್ನಾ ಮಾಡಬಹುದೇ?",
        "ಸರಿ, ಶುಕ್ರವಾರ ಪಾವತಿಸುತ್ತೇನೆ.",
        "ಹೌದು, ಸರಿ.",
    ],
}
#: name -> (MOCK_BUGS, language, interrupt greeting)
CONFIGS: dict[str, tuple[str, str, bool]] = {
    "00_clean_en": ("", "en-IN", False),
    "01_no_disclosure": ("no_disclosure", "en-IN", False),
    "02_no_amount_confirm": ("no_amount_confirm", "en-IN", False),
    "03a_clean_kn": ("", "kn-IN", False),
    "03b_english_to_kannada": ("english_to_kannada", "kn-IN", False),
    "04a_clean_interrupt": ("", "en-IN", True),
    "04b_ignore_interrupt": ("ignore_interrupt", "en-IN", True),
    "05_false_waiver": ("false_waiver", "en-IN", False),
}
SILENCE = bytes(AUDIO_FRAME_BYTES)


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)


class Track:
    """PCM placed on the wall-clock timeline (gaps are silence)."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def put(self, t_s: float, frame: bytes) -> None:
        pos = int(t_s * 16000) * 2
        if len(self.buf) < pos:
            self.buf += bytes(pos - len(self.buf))
        self.buf += frame


def mix(a: bytes, b: bytes) -> bytes:
    n = max(len(a), len(b)) // 2
    import array

    x, y = array.array("h"), array.array("h")
    x.frombytes(a.ljust(n * 2, b"\0"))
    y.frombytes(b.ljust(n * 2, b"\0"))
    return array.array("h", (max(-32768, min(32767, i + j)) for i, j in zip(x, y))).tobytes()


async def run_call(port: int, lang: str, interrupt: bool, tts: GnaniSpeech) -> dict:
    lines = [
        wav_to_pcm(tts.synthesize(t, CALLER_VOICE, lang, sample_rate=16000).audio)
        for t in LINES[lang]
    ]
    agent_track, caller_track = Track(), Track()
    messages: list[dict] = []
    state = {
        "last_audio": -1.0,
        "first_audio": 0.0,
        "agent_turns": 0,
        "bursts": 0,
        "ended": False,
    }
    t0 = time.monotonic()

    async with connect(f"ws://127.0.0.1:{port}/call", max_size=2**20) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "start",
                    "protocol": "pareeksha-audio-v1",
                    "call_id": "00000000-0000-4000-8000-000000000003",
                    "sample_rate": 16000,
                    "language_hint": lang,
                    "metadata": {},
                }
            )
        )

        async def reader() -> None:
            try:
                async for msg in ws:
                    now = time.monotonic() - t0
                    if isinstance(msg, bytes):
                        agent_track.put(now, msg)
                        if now - state["last_audio"] > 0.5:
                            state["bursts"] += 1
                        state["last_audio"] = now
                        state["first_audio"] = state["first_audio"] or now + 1e-6
                    else:
                        m = json.loads(msg)
                        m["wall_s"] = round(now, 2)
                        messages.append(m)
                        if m["type"] == "transcript" and m["role"] == "agent":
                            state["agent_turns"] += 1
                        if m["type"] == "call_end":
                            state["ended"] = True
            except Exception as exc:
                print("reader stopped:", repr(exc), flush=True)
                state["ended"] = True

        rtask = asyncio.create_task(reader())
        queue = list(lines)
        playing: bytes | None = None
        offset = 0
        deadline = time.monotonic() + 90
        interrupted = False
        played = 0
        last_line: bytes | None = None
        turns_at_last_line = 0
        last_line_end = 0.0
        next_at = time.monotonic()
        while not state["ended"] and time.monotonic() < deadline:
            now = time.monotonic() - t0
            if (
                playing is None
                and last_line is not None
                and state["agent_turns"] <= turns_at_last_line
                and state["last_audio"] > 0
                and now - state["last_audio"] > 4.0
                and now - last_line_end > 4.0
            ):
                # The agent never answered (it ignored the interruption): the caller repeats.
                queue.insert(0, last_line)
                played -= 1
                turns_at_last_line = state["agent_turns"] + 1  # repeat only once
            if playing is None and queue:
                heard_reply = state["bursts"] > played
                quiet = heard_reply and now - state["last_audio"] > 0.9
                barge = (
                    interrupt
                    and not interrupted
                    and state["first_audio"]
                    and now - state["first_audio"] > 1.5
                )
                if quiet or barge:
                    playing, offset = queue.pop(0), 0
                    last_line, turns_at_last_line = playing, state["agent_turns"]
                    played += 1
                    interrupted = interrupted or bool(barge)
            if playing is not None:
                frame = playing[offset : offset + AUDIO_FRAME_BYTES].ljust(AUDIO_FRAME_BYTES, b"\0")
                offset += AUDIO_FRAME_BYTES
                if offset >= len(playing):
                    playing = None
                    last_line_end = now
            else:
                frame = SILENCE
            await ws.send(frame)
            caller_track.put(now, frame)
            next_at += AUDIO_FRAME_MS / 1000
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))
        await asyncio.sleep(0.5)
        await ws.close()
        rtask.cancel()
    return {
        "messages": messages,
        "agent_pcm": bytes(agent_track.buf),
        "caller_pcm": bytes(caller_track.buf),
        "caller_lines": LINES[lang],
        "interrupt": interrupt,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "proof/VOICE-03/calls")
    ap.add_argument("--only", nargs="*", help="config names to run")
    args = ap.parse_args()
    if not os.environ.get("GNANI_API_KEY"):
        sys.exit("GNANI_API_KEY is not set")
    cache = Path(os.environ.get("MOCK_AGENT_TTS_CACHE", "/tmp/mock_agent_tts"))
    caller_ledger = UsageLedger()
    tts = GnaniSpeech(os.environ["GNANI_API_KEY"], cache_dir=cache, ledger=caller_ledger)
    for i, (name, (bugs, lang, interrupt)) in enumerate(CONFIGS.items()):
        if args.only and name not in args.only:
            continue
        port = 8800 + i
        out = args.out / name
        out.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "MOCK_BUGS": bugs,
            "MOCK_AGENT_PORT": str(port),
            "MOCK_AGENT_TTS_CACHE": str(cache),
            "PYTHONPATH": f"{ROOT}:{ROOT / 'backend'}",
        }
        log = (out / "server.log").open("w")
        server = subprocess.Popen(
            [sys.executable, "-m", "mock_agent.server"],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )
        try:
            for _ in range(50):
                time.sleep(0.2)
                try:
                    import urllib.request

                    urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                    break
                except OSError:
                    continue
            result = asyncio.run(run_call(port, lang, interrupt, tts))
            time.sleep(0.5)
        finally:
            server.terminate()
            server.wait(10)
            log.close()
        write_wav(out / "agent.wav", result["agent_pcm"])
        write_wav(out / "caller.wav", result["caller_pcm"])
        write_wav(out / "mixed.wav", mix(result["agent_pcm"], result["caller_pcm"]))
        meta = {k: result[k] for k in ("messages", "caller_lines", "interrupt")}
        meta.update(
            config=name,
            mock_bugs=bugs,
            language=lang,
            agent_seconds=len(result["agent_pcm"]) / 32000,
        )
        (out / "transcript.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(name, "done", flush=True)
    (args.out / "caller_tts_usage.json").write_text(json.dumps(caller_ledger.totals(), indent=2))


if __name__ == "__main__":
    main()
