"""Render SNR table + 8 profile WAVs from a synthetic clip.

Run from backend/:  python3 ../proof/VOICE-02/render_proof.py
"""

import pathlib

import soundfile as sf

from pareeksha.audio import BUILTIN_PROFILES, LineSimulator, dsp
from tests.fixtures.synth_audio import RATE, synth_speech

out = pathlib.Path(__file__).parent / "audio"
out.mkdir(exist_ok=True)
x = synth_speech(4.0, seed=1)
sf.write(out / "input_synthetic.wav", x, RATE, subtype="PCM_16")
print(f"{'profile':26s} target  measured  len_in len_out")
for name, p in BUILTIN_PROFILES.items():
    y, st = LineSimulator.simulate(p, x, seed=0, capture=True)
    sf.write(out / f"{name}.wav", y, RATE, subtype="PCM_16")
    if p.background:
        m = dsp.measure_snr_db(st["speech"], st["noise_applied"], p.sample_rate)
    else:
        m = float("nan")
    tgt = p.snr_db if p.snr_db is not None else "-"
    print(f"{name:26s} {tgt!s:>6}  {m:8.3f}  {len(x)} {len(y)}")
