import array
import io
import wave

import pytest
from mock_agent.speech import pcm_to_wav, wav_to_pcm
from mock_agent.vad import UtteranceDetector, rms

LOUD = array.array("h", [4000, -4000] * 160).tobytes()
QUIET = bytes(640)


def test_rms() -> None:
    assert rms(QUIET) == 0.0
    assert rms(LOUD) > 3000
    assert rms(b"") == 0.0


def test_utterance_detected_after_silence() -> None:
    vad = UtteranceDetector()
    out = [vad.feed(LOUD) for _ in range(20)]
    assert all(o is None for o in out) and vad.speaking
    results = [vad.feed(QUIET) for _ in range(40)]
    utterance = next(r for r in results if r is not None)
    assert len(utterance) >= 20 * 640
    assert not vad.speaking


def test_blip_is_ignored() -> None:
    vad = UtteranceDetector()
    vad.feed(LOUD)
    assert all(vad.feed(QUIET) is None for _ in range(60))


def test_wav_roundtrip() -> None:
    pcm = LOUD * 3
    wav = pcm_to_wav(pcm)
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
    assert wav_to_pcm(wav) == pcm


class _FakeGnani:
    def transcribe(self, wav: bytes, language: str) -> dict[str, str]:
        return {"transcript": f"heard {language} {len(wav)}"}

    def synthesize(self, text: str, voice: str, language: str, **_: int) -> "_FakeTTS":
        return _FakeTTS(pcm_to_wav(LOUD))


class _FakeTTS:
    def __init__(self, audio: bytes) -> None:
        self.audio = audio


async def test_gnani_agent_speech_wraps_shared_client() -> None:
    from pathlib import Path

    from mock_agent.speech import GnaniAgentSpeech

    speech = GnaniAgentSpeech(cache_dir=Path("/nonexistent-cache"))
    speech._gnani = _FakeGnani()  # type: ignore[assignment]
    assert (await speech.hear(LOUD, "kn-IN")).startswith("heard kn-IN")
    assert await speech.say("hi", "en-IN") == LOUD
    assert speech.usage_totals() == {}


async def test_stt_is_retried_when_the_provider_answers_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mock_agent import speech as speech_module

    calls: list[int] = []

    class Flaky:
        def transcribe(self, wav: bytes, language: str) -> dict[str, str]:
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("429 Too Many Requests")
            return {"transcript": "yes speaking"}

    monkeypatch.setattr(speech_module, "STT_RETRY_S", 0.0)
    engine = speech_module.GnaniAgentSpeech.__new__(speech_module.GnaniAgentSpeech)
    engine._gnani = Flaky()  # type: ignore[assignment]
    assert await engine.hear(b"\x00\x00" * 160, "en-IN") == "yes speaking"
    assert len(calls) == 3


# --- EVAL-07 / ISSUE-1: a steady noise bed must not hold the utterance open ---------------------

import math  # noqa: E402
import random  # noqa: E402


def _noise_frame(rng: random.Random, level: float) -> bytes:
    return array.array("h", [int(rng.gauss(0, level)) for _ in range(320)]).tobytes()


def _speech_frame(rng: random.Random, level: float, noise: float, i: int) -> bytes:
    """220 Hz tone, 4 Hz syllable envelope (pauses between syllables), on top of the noise."""
    out = []
    for n in range(320):
        t = (i * 320 + n) / 16000
        env = max(0.0, math.sin(2 * math.pi * 4 * t))
        out.append(int(level * env * math.sin(2 * math.pi * 220 * t) + rng.gauss(0, noise)))
    return array.array("h", [max(-32768, min(32767, s)) for s in out]).tobytes()


def _run(vad: UtteranceDetector, frames: list[bytes]) -> list[tuple[int, bytes]]:
    return [(i, u) for i, f in enumerate(frames) if (u := vad.feed(f)) is not None]


@pytest.mark.parametrize("noise", [1200.0, 2500.0])  # both far above the absolute threshold of 500
def test_babble_bed_does_not_keep_the_utterance_open(noise: float) -> None:
    rng = random.Random(7)
    bed = [
        _noise_frame(rng, noise) for _ in range(150)
    ]  # 3 s of line noise before the caller speaks
    turn = [_speech_frame(rng, noise * 6, noise, i) for i in range(100)]  # 2 s of speech (+15 dB)
    after = [_noise_frame(rng, noise) for _ in range(100)]  # 2 s of noise again
    frames = bed + turn + after
    old = _run(UtteranceDetector(noise_ratio=0.0), frames)  # no noise floor, fixed threshold only
    new = _run(UtteranceDetector(), frames)
    assert old == []  # the noise reads as speech that never ends: the agent never answers
    assert len(new) == 1
    end, utterance = new[0]
    assert 250 <= end <= 300  # closed in the noise after the turn (frames 250..349)
    assert len(utterance) >= 50 * 640  # most of the 2 s turn is in it


def test_noise_from_the_first_frame_gives_no_utterance_and_no_floor_until_measured() -> None:
    rng = random.Random(5)
    vad = UtteranceDetector()
    assert not vad.noise_known
    got = _run(vad, [_noise_frame(rng, 2500.0) for _ in range(200)])
    assert vad.noise_known
    assert got == []  # the warm-up "utterance" was noise once the floor was known: dropped


def test_steady_noise_alone_is_not_speech() -> None:
    rng = random.Random(3)
    vad = UtteranceDetector()
    assert _run(vad, [_noise_frame(rng, 2000.0) for _ in range(1000)]) == []  # 20 s
