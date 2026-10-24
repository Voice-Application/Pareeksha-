"""VOICE-02 acceptance: SNR +/-0.5 dB, determinism, chunked == whole, 8 distinct profiles."""

from __future__ import annotations

import audioop
import itertools
from typing import Any

import numpy as np
import pytest

from pareeksha.audio import (
    BUILTIN_PROFILES,
    LineProfile,
    LineSimulator,
    dsp,
    get_profile,
)
from pareeksha.audio.noise import CATEGORIES, NoiseSource
from tests.fixtures.synth_audio import RATE, spectrum_db, synth_speech

NOISY = [p for p in BUILTIN_PROFILES.values() if p.background]


@pytest.fixture(scope="module")
def speech() -> np.ndarray:
    return synth_speech(10.0, seed=1)


def test_eight_profiles_match_rubric():
    assert list(BUILTIN_PROFILES) == [
        "clean_16k",
        "pstn_8k_alaw",
        "pstn_office_babble_15db",
        "pstn_street_10db",
        "pstn_market_5db",
        "mobile_bus_5db",
        "mobile_weak_signal",
        "auto_rickshaw_0db",
    ]
    p = get_profile("mobile_weak_signal")
    assert (
        p.sample_rate,
        p.codec,
        p.pstn_bandpass,
        p.background,
        p.snr_db,
        p.packet_loss_pct,
        p.clipping,
    ) == (
        8000,
        "alaw",
        True,
        "street_traffic",
        10,
        5,
        True,
    )


def test_profile_validation():
    with pytest.raises(ValueError):
        LineProfile(name="x", codec="gsm")
    with pytest.raises(ValueError):
        LineProfile(name="x", background="street_traffic")  # snr missing
    with pytest.raises(KeyError):
        get_profile("nope")


@pytest.mark.parametrize("profile", NOISY, ids=lambda p: p.name)
def test_snr_within_half_db_offline(profile, speech):
    y, stages = LineSimulator.simulate(profile, speech, seed=7, capture=True)
    assert len(y) == len(speech)
    snr = dsp.measure_snr_db(stages["speech"], stages["noise_applied"], profile.sample_rate)
    assert abs(snr - profile.snr_db) <= 0.5


@pytest.mark.parametrize("profile", NOISY, ids=lambda p: p.name)
def test_snr_within_half_db_streaming_with_reference_power(profile, speech):
    """Streaming path with the caller's known reference speech power (utterance-level)."""
    ref = LineSimulator(profile, seed=3, capture=True)
    ref.process(speech)
    ref.flush()
    c = ref.captured
    mask = dsp.active_mask(c["speech"], profile.sample_rate)
    ps = dsp.power(c["speech"][mask])
    sim = LineSimulator(
        profile, seed=3, speech_power=ps, capture=True
    )  # unit-noise calibration only
    for i in range(0, len(speech), 320):
        sim.process(speech[i : i + 320])
    sim.flush()
    c2 = sim.captured
    snr = dsp.measure_snr_db(c2["speech"], c2["noise_applied"], profile.sample_rate)
    assert abs(snr - profile.snr_db) <= 0.5


def test_mix_at_snr_exact():
    rng = np.random.default_rng(0)
    s = synth_speech(5.0, seed=2)
    n = rng.standard_normal(RATE * 3).astype(np.float32)
    for target in (0, 5, 10, 15, -3):
        mixed = dsp.mix_at_snr(s, n, target, RATE)
        noise = mixed - s
        assert abs(dsp.measure_snr_db(s, noise, RATE) - target) < 0.01


@pytest.mark.parametrize("profile", list(BUILTIN_PROFILES.values()), ids=lambda p: p.name)
def test_deterministic_same_seed(profile, speech):
    a = LineSimulator.simulate(profile, speech, seed=11)
    b = LineSimulator.simulate(profile, speech, seed=11)
    assert np.array_equal(a, b)


def test_different_seed_changes_noise_and_loss(speech):
    p = get_profile("mobile_bus_5db")
    assert not np.array_equal(
        LineSimulator.simulate(p, speech, seed=1),
        LineSimulator.simulate(p, speech, seed=2),
    )


@pytest.mark.parametrize("profile", list(BUILTIN_PROFILES.values()), ids=lambda p: p.name)
@pytest.mark.parametrize("chunk", [320, 100, 777, 5000])
def test_chunked_equals_whole(profile, chunk, speech):
    clip = speech[: RATE * 4 + 13]  # odd tail on purpose
    whole = LineSimulator(profile, seed=5)
    expected = np.concatenate([whole.process(clip), whole.flush()])
    sim = LineSimulator(profile, seed=5)
    parts = [sim.process(clip[i : i + chunk]) for i in range(0, len(clip), chunk)]
    parts.append(sim.flush())
    got = np.concatenate(parts)
    assert len(got) == len(clip)
    assert np.array_equal(got, expected)


def test_chunked_equals_whole_with_fixed_reference(speech):
    p = get_profile("pstn_market_5db")
    whole = LineSimulator.simulate(p, speech, seed=9)
    ref = LineSimulator(p, seed=9, capture=True)
    ref.process(speech)
    ref.flush()
    c = ref.captured
    mask = dsp.active_mask(c["speech"], 8000)
    kw: dict[str, Any] = {
        "speech_power": dsp.power(c["speech"][mask]),
        "noise_power": dsp.power(c["noise_raw"][mask]),
    }
    sim = LineSimulator(p, seed=9, **kw)
    parts = [sim.process(speech[i : i + 640]) for i in range(0, len(speech), 640)] + [sim.flush()]
    assert np.array_equal(np.concatenate(parts), whole)


def test_clean_profile_is_exact_passthrough(speech):
    y = LineSimulator.simulate(get_profile("clean_16k"), speech)
    assert np.array_equal(y, speech)


def _lag(y, x):
    n = RATE * 3
    return int(np.argmax(np.correlate(y[:n], x[:n], mode="full"))) - (n - 1)


def test_output_time_aligned_with_input(speech):
    # Resample down/up with no band-pass: delay fully compensated.
    p = LineProfile(name="r", sample_rate=8000)
    assert _lag(LineSimulator.simulate(p, speech), speech) == 0
    # PSTN band-pass adds only its natural IIR group delay (< 2.5 ms).
    assert abs(_lag(LineSimulator.simulate(get_profile("pstn_8k_alaw"), speech), speech)) <= 40


def test_pstn_band_limits_spectrum(speech):
    y = LineSimulator.simulate(get_profile("pstn_8k_alaw"), speech)
    from scipy import signal

    f, p = signal.welch(y, fs=RATE, nperseg=2048)
    inband = p[(f >= 500) & (f <= 3000)].mean()
    assert p[f > 4200].mean() < inband * 1e-3  # nothing above the 8 kHz-rate Nyquist
    assert p[f < 120].mean() < inband * 1e-2


def test_alaw_matches_stdlib_and_quantises():
    x = (np.sin(np.linspace(0, 200, 8000)) * 0.4).astype(np.float32)
    y = dsp.codec_roundtrip(x, "alaw")
    expected = audioop.alaw2lin(audioop.lin2alaw(dsp.float_to_pcm16(x), 2), 2)
    assert dsp.float_to_pcm16(y) == expected
    assert not np.array_equal(x, y)
    assert np.max(np.abs(x - y)) < 0.03
    z = dsp.codec_roundtrip(x, "mulaw")
    assert not np.array_equal(y, z)


def test_clipping_flattens_peaks(speech):
    from pareeksha.audio.line_simulator import CLIP_CEILING

    p = LineProfile(name="c", sample_rate=8000, codec="none", pstn_bandpass=True, clipping=True)
    y = LineSimulator.simulate(p, speech)
    assert np.max(np.abs(y)) <= CLIP_CEILING * 1.5  # up-sampling Gibbs overshoot only
    assert np.mean(np.abs(y) > CLIP_CEILING * 0.9) > 0.001


@pytest.mark.parametrize("loss", [2.0, 5.0])
def test_packet_loss_rate(loss):
    p = LineProfile(name="l", sample_rate=8000, codec="none", packet_loss_pct=loss)
    tone = (0.3 * np.sin(2 * np.pi * 440 * np.arange(RATE * 120) / RATE)).astype(np.float32)
    sim = LineSimulator(p, seed=4)
    y = np.concatenate([sim.process(tone), sim.flush()])
    frames = y[: len(y) // 320 * 320].reshape(-1, 320)
    # a dropped frame is silent apart from resampler ringing at its edges
    dropped = np.mean(np.abs(frames[:, 100:220]), axis=1) < 1e-4
    rate = dropped.mean() * 100
    assert 0.5 * loss <= rate <= 1.6 * loss


@pytest.mark.parametrize("category", CATEGORIES)
def test_noise_unit_power_and_seeded(category):
    a = NoiseSource(category, 8000, 1).generate(8000 * 20)
    assert abs(10 * np.log10(np.mean(a**2))) < 0.7
    b = NoiseSource(category, 8000, 1).generate(8000 * 20)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, NoiseSource(category, 8000, 2).generate(8000 * 20))


def test_noise_categories_spectrally_distinct():
    spectra = {
        c: spectrum_db(NoiseSource(c, 8000, 2).generate(8000 * 10), rate=8000) for c in CATEGORIES
    }
    for a, b in itertools.combinations(CATEGORIES, 2):
        d = np.mean(np.abs(spectra[a] - spectra[b]))
        assert d > 1.5, (a, b, d)


def test_all_eight_profiles_audible_and_distinct(speech):
    outs = {n: LineSimulator.simulate(p, speech, seed=0) for n, p in BUILTIN_PROFILES.items()}
    for n, y in outs.items():
        assert np.sqrt(np.mean(y**2)) > 0.01, n  # audible
        assert np.max(np.abs(y)) <= 1.0
    for (na, a), (nb, b) in itertools.combinations(outs.items(), 2):
        diff = np.sqrt(np.mean((a - b) ** 2)) / np.sqrt(np.mean(a**2))
        assert diff > 0.05, (na, nb, diff)


def test_pcm16_helpers_roundtrip(speech):
    p = get_profile("pstn_street_10db")
    sim = LineSimulator(p, seed=1)
    pcm = dsp.float_to_pcm16(speech[:3200])
    out = sim.process_pcm16(pcm) + dsp.float_to_pcm16(sim.flush())
    assert len(out) == len(pcm)
