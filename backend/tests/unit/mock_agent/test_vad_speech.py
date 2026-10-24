import array
import io
import wave

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
