# NOTES

- VOICE-02: LineSimulator re-blocks input into fixed 20 ms frames, so chunked==whole is bit-exact; streaming SNR uses a causal speech-power estimate unless `speech_power`/`noise_power` are given (`LineSimulator.simulate` does a two-pass exact calibration). Noise beds are procedural (no licensed clips); band-pass IIR leaves ~1.4 ms group delay (resamplers are delay-compensated). See `proof/VOICE-02/proof.md`.
