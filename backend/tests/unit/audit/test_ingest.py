"""Recording ingest: format sniffing, size limit, conversion to 16 kHz mono (FR-AU-1)."""

from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf

from pareeksha.audit.ingest import (
    MAX_UPLOAD_BYTES,
    AudioError,
    AudioTooLargeError,
    check_size,
    decode_audio,
    sniff_format,
)
from pareeksha.speech.wav import wav_info


def tone(seconds: float, freq: float, rate: int) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32")


def encode(samples: np.ndarray, rate: int, fmt: str, subtype: str | None = None) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format=fmt, subtype=subtype)
    return buf.getvalue()


def test_sniff_by_content_not_name() -> None:
    assert sniff_format(encode(tone(0.5, 300, 8000), 8000, "WAV")) == "wav"
    assert sniff_format(encode(tone(0.5, 300, 16000), 16000, "MP3")) == "mp3"
    assert sniff_format(b"ID3\x04\x00") == "mp3"
    for junk in (b"", b"OggS....", b"fLaC....", b"RIFF\x00\x00\x00\x00AVI LIST"):
        with pytest.raises(AudioError, match="WAV and MP3"):
            sniff_format(junk)


def test_size_limit_is_ten_megabytes() -> None:
    check_size(b"x" * MAX_UPLOAD_BYTES)
    with pytest.raises(AudioTooLargeError, match="10 MB"):
        check_size(b"x" * (MAX_UPLOAD_BYTES + 1))
    with pytest.raises(AudioError, match="empty"):
        check_size(b"")
    assert issubclass(AudioTooLargeError, AudioError)


def test_wav_8k_mono_is_resampled_to_16k_mono() -> None:
    out = decode_audio(encode(tone(2.0, 440, 8000), 8000, "WAV"))
    assert out.format == "wav" and out.source_rate == 8000 and out.source_channels == 1
    assert out.channel_wavs == ()
    rate, seconds = wav_info(out.mixed_wav)
    assert rate == 16000 and seconds == pytest.approx(2.0, abs=0.01)
    assert out.duration_s == pytest.approx(2.0, abs=0.001)


def test_mp3_decodes() -> None:
    out = decode_audio(encode(tone(1.5, 500, 16000), 16000, "MP3"))
    assert out.format == "mp3"
    rate, seconds = wav_info(out.mixed_wav)
    assert rate == 16000 and seconds == pytest.approx(1.5, abs=0.1)


def test_stereo_keeps_each_channel_and_mixes_down() -> None:
    left, right = tone(1.0, 300, 16000), tone(1.0, 900, 16000)
    out = decode_audio(encode(np.stack([left, right], axis=1), 16000, "WAV"))
    assert out.source_channels == 2 and len(out.channel_wavs) == 2
    for wav in out.channel_wavs:
        rate, seconds = wav_info(wav)
        assert rate == 16000 and seconds == pytest.approx(1.0, abs=0.01)
    first = np.frombuffer(out.channel_wavs[0][44:], dtype="<i2").astype("float32")
    second = np.frombuffer(out.channel_wavs[1][44:], dtype="<i2").astype("float32")
    # the 300 Hz tone sits in channel 0 only, the 900 Hz tone in channel 1 only
    spec0, spec1 = np.abs(np.fft.rfft(first)), np.abs(np.fft.rfft(second))
    assert abs(int(np.argmax(spec0)) - 300) <= 2 and abs(int(np.argmax(spec1)) - 900) <= 2


def test_corrupt_and_unusable_audio_is_rejected() -> None:
    with pytest.raises(AudioError, match="cannot decode"):
        decode_audio(b"RIFF\x24\x00\x00\x00WAVEfmt garbage garbage garbage")
    with pytest.raises(AudioError, match="too short"):
        decode_audio(encode(tone(0.1, 300, 16000), 16000, "WAV"))
    with pytest.raises(AudioError, match="channels"):
        decode_audio(encode(np.zeros((16000, 3), dtype="float32") + 0.1, 16000, "WAV"))
