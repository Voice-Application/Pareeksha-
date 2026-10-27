"""Recording ingest: format check and conversion to 16 kHz mono 16-bit WAV (FR-AU-1).

Uploads are WAV or MP3 up to 10 MB. Everything downstream (batch STT, the playback copy stored as
``calls.recording_mixed``) works on 16 kHz mono PCM, so the original is decoded once here.
Decoding uses libsndfile through ``soundfile`` (WAV and MP3), so no external binary is needed.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from math import gcd
from typing import Literal

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from pareeksha.speech.wav import pcm_to_wav

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
TARGET_RATE = 16000
MIN_DURATION_S = 0.3

AudioFormat = Literal["wav", "mp3"]


class AudioError(ValueError):
    """The recording cannot be used (maps to ``422 unsupported_audio``)."""


class AudioTooLargeError(AudioError):
    """Over ``MAX_UPLOAD_BYTES`` (maps to ``413 file_too_large``)."""


@dataclass(frozen=True)
class DecodedAudio:
    format: AudioFormat
    #: Mono mix at 16 kHz, WAV container (playback copy and the input of diarized STT).
    mixed_wav: bytes
    #: One mono 16 kHz WAV per source channel when the file has two (else empty).
    channel_wavs: tuple[bytes, ...]
    duration_s: float
    source_rate: int
    source_channels: int


def sniff_format(data: bytes) -> AudioFormat:
    """Identify WAV or MP3 from the bytes (not from the file name or declared content type)."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    raise AudioError("unsupported audio: only WAV and MP3 recordings are accepted")


def check_size(data: bytes) -> None:
    if len(data) > MAX_UPLOAD_BYTES:
        raise AudioTooLargeError(f"recording is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not data:
        raise AudioError("recording is empty")


def _to_target_rate(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == TARGET_RATE:
        return x
    g = gcd(TARGET_RATE, rate)
    out: np.ndarray = resample_poly(x, TARGET_RATE // g, rate // g)
    return out


def _to_wav(x: np.ndarray) -> bytes:
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    return pcm_to_wav(pcm.tobytes(), TARGET_RATE)


def decode_audio(data: bytes) -> DecodedAudio:
    """Validate and convert a recording; raises :class:`AudioError` on anything unusable."""
    check_size(data)
    fmt = sniff_format(data)
    try:
        samples, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except (sf.LibsndfileError, RuntimeError, ValueError) as exc:
        raise AudioError(
            f"unsupported audio: cannot decode the {fmt.upper()} file ({exc})"
        ) from exc
    frames, channels = samples.shape
    if frames == 0 or frames / rate < MIN_DURATION_S:
        raise AudioError("recording is too short to transcribe")
    if channels > 2:
        raise AudioError(f"unsupported audio: {channels} channels (mono or stereo only)")
    resampled = _to_target_rate(samples, rate)
    mixed = resampled.mean(axis=1)
    per_channel = tuple(_to_wav(resampled[:, c]) for c in range(channels)) if channels == 2 else ()
    return DecodedAudio(
        format=fmt,
        mixed_wav=_to_wav(mixed),
        channel_wavs=per_channel,
        duration_s=frames / rate,
        source_rate=int(rate),
        source_channels=int(channels),
    )
