"""LineSimulator: degrade outgoing 16 kHz caller audio to a named line condition.

Per 20 ms frame (docs/03-TRD.md §6): resample to profile rate -> 300-3400 Hz
band-pass -> background noise at the target SNR (measured on speech-active
samples) -> optional clipping -> G.711 codec round trip -> optional packet loss
(drop whole 20 ms frames) -> resample back to 16 kHz.

Determinism: all randomness derives from `seed`; input is re-blocked internally
into fixed 20 ms frames, so any chunking of the input yields bit-identical
output to processing the whole file at once. Output is time-aligned with the
input (resampler delay compensated) and has exactly the input length after
`flush()`.
"""

from __future__ import annotations

import numpy as np

from pareeksha.audio import dsp
from pareeksha.audio.noise import NoiseSource
from pareeksha.audio.profiles import LineProfile

CLIP_DRIVE = 4.0
CLIP_CEILING = 0.5
_ACTIVE_POWER_THRESHOLD = 10 ** (dsp.ACTIVE_THRESHOLD_DBFS / 10.0)


class LineSimulator:
    def __init__(
        self,
        profile: LineProfile,
        seed: int = 0,
        *,
        speech_power: float | None = None,
        noise_power: float | None = None,
        capture: bool = False,
    ):
        """
        speech_power: fixed reference speech power (active samples, at the profile rate,
            after band-pass). When None the simulator estimates it causally from the
            speech seen so far (nominal level until the first speech frame).
        noise_power: measured power of the unit noise stream on active samples (1.0 by default).
        capture: record the speech and noise stages (for tests/diagnostics).
        """
        self.profile = profile
        self.seed = seed
        self._rate = profile.sample_rate
        self._frame = dsp.PIPELINE_RATE * dsp.FRAME_MS // 1000
        self._identity = profile.is_identity
        self._speech_power = speech_power
        self._noise_power = 1.0 if noise_power is None else noise_power
        self._capture = capture
        self._cap: dict[str, list[np.ndarray]] = {
            "speech": [],
            "noise_raw": [],
            "noise_applied": [],
        }

        ss = np.random.SeedSequence(seed)
        noise_ss, loss_ss = ss.spawn(2)
        self._loss_rng = np.random.default_rng(loss_ss)
        self._noise = (
            NoiseSource(
                profile.background, self._rate, int(noise_ss.generate_state(1)[0])
            )
            if profile.background
            else None
        )
        self._down = (
            dsp.StreamingResampler("down") if self._rate != dsp.PIPELINE_RATE else None
        )
        self._up = (
            dsp.StreamingResampler("up") if self._rate != dsp.PIPELINE_RATE else None
        )
        self._bandpass = (
            dsp.StreamingBandpass(self._rate) if profile.pstn_bandpass else None
        )
        # Group delay of down + up FIR at the 16 kHz pipeline rate.
        self._latency = 2 * dsp.StreamingResampler.FIR_DELAY if self._down else 0
        self._skip = self._latency
        self._acc_sum = 0.0
        self._acc_n = 0
        self._buf = np.zeros(0, dtype=np.float32)
        self._total_in = 0
        self._total_out = 0
        self._flushed = False

    # ------------------------------------------------------------------ public

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Feed float32 16 kHz samples; returns the output that is ready (maybe empty)."""
        if self._flushed:
            raise RuntimeError("LineSimulator already flushed; create a new instance")
        x = np.asarray(audio, dtype=np.float32)
        if self._identity:
            self._total_in += len(x)
            self._total_out += len(x)
            return x.copy()
        self._total_in += len(x)
        self._buf = np.concatenate([self._buf, x])
        out: list[np.ndarray] = []
        while len(self._buf) >= self._frame:
            frame, self._buf = self._buf[: self._frame], self._buf[self._frame :]
            out.append(self._emit(self._process_frame(frame)))
        return self._concat(out)

    def flush(self) -> np.ndarray:
        """Drain buffered/filter-delayed samples so total output length == total input length."""
        if self._flushed or self._identity:
            self._flushed = True
            return np.zeros(0, dtype=np.float32)
        self._flushed = True
        self._buf = np.concatenate(
            [self._buf, np.zeros(self._latency, dtype=np.float32)]
        )
        out: list[np.ndarray] = []
        while len(self._buf) > 0:
            frame, self._buf = self._buf[: self._frame], self._buf[self._frame :]
            out.append(self._emit(self._process_frame(frame)))
        y = self._concat(out)
        excess = self._total_out - self._total_in
        return y[: len(y) - excess] if excess > 0 else y

    def process_pcm16(self, data: bytes) -> bytes:
        return dsp.float_to_pcm16(self.process(dsp.pcm16_to_float(data)))

    @property
    def captured(self) -> dict[str, np.ndarray]:
        return {
            k: (np.concatenate(v) if v else np.zeros(0, dtype=np.float32))
            for k, v in self._cap.items()
        }

    @classmethod
    def simulate(
        cls,
        profile: LineProfile,
        audio: np.ndarray,
        seed: int = 0,
        *,
        capture: bool = False,
    ):
        """Whole-clip convenience. Two passes calibrate speech/noise power so the
        mixed SNR is exact (the streaming path estimates it causally).
        With capture=True returns (output, stages) where stages has speech/noise_raw/noise_applied."""
        audio = np.asarray(audio, dtype=np.float32)
        kwargs: dict = {}
        if profile.background:
            ref = cls(profile, seed, capture=True)
            ref.process(audio)
            ref.flush()
            c = ref.captured
            mask = dsp.active_mask(c["speech"], profile.sample_rate)
            ps = (
                dsp.power(c["speech"][mask]) if mask.any() else dsp.NOMINAL_SPEECH_POWER
            )
            pn = dsp.power(c["noise_raw"][mask]) if mask.any() else 1.0
            kwargs = {"speech_power": ps, "noise_power": pn}
        sim = cls(profile, seed, capture=capture, **kwargs)
        y = np.concatenate([sim.process(audio), sim.flush()])
        return (y, sim.captured) if capture else y

    # ---------------------------------------------------------------- internals

    @staticmethod
    def _concat(parts: list[np.ndarray]) -> np.ndarray:
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def _emit(self, y: np.ndarray) -> np.ndarray:
        if self._skip:
            drop = min(self._skip, len(y))
            y = y[drop:]
            self._skip -= drop
        self._total_out += len(y)
        return y

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        p = self.profile
        x = self._down.process(frame) if self._down else frame
        if self._bandpass:
            x = self._bandpass.process(x)
        if self._noise is not None and len(x):
            raw = self._noise.generate(len(x))
            if self._speech_power is not None:
                ps = self._speech_power
            else:
                if dsp.power(x) > _ACTIVE_POWER_THRESHOLD:
                    self._acc_sum += float(np.sum(np.square(x, dtype=np.float64)))
                    self._acc_n += len(x)
                ps = (
                    self._acc_sum / self._acc_n
                    if self._acc_n
                    else dsp.NOMINAL_SPEECH_POWER
                )
            g = dsp.noise_gain(ps, self._noise_power, p.snr_db)
            applied = (g * raw).astype(np.float32)
            if self._capture:
                self._cap["speech"].append(x.copy())
                self._cap["noise_raw"].append(raw)
                self._cap["noise_applied"].append(applied)
            x = x + applied
        elif self._capture:
            self._cap["speech"].append(x.copy())
            self._cap["noise_raw"].append(np.zeros(len(x), dtype=np.float32))
            self._cap["noise_applied"].append(np.zeros(len(x), dtype=np.float32))
        if p.clipping:
            x = dsp.hard_clip(x, CLIP_DRIVE, CLIP_CEILING)
        x = dsp.codec_roundtrip(x, p.codec)
        if (
            p.packet_loss_pct > 0.0
            and self._loss_rng.random() < p.packet_loss_pct / 100.0
        ):
            x = np.zeros_like(x)
        return self._up.process(x) if self._up else x.astype(np.float32)
