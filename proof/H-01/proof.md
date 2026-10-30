# H-01 proof: owner keys work (STATUS: done-unverified)

AGENTS.md section 7, H-01: "Gnani + Gemini keys in `.env`; Timbre v3.0 access confirmed; Gemini model ID pinned;
`SECRET_KEY` generated." Evidence below records HTTP status codes and model ids only. No key value appears in this
folder (checked: `grep -rF` of each key value over `proof/H-01` returns nothing).

## Fresh check (2026-10-30, this session)
Command: `set -a; . ./.env; set +a; .venv-verify/bin/python proof/H-01/key_check.py` (keys come only from the environment).
Real output: `proof/H-01/key_check.txt`.

| Provider | Call | Result |
|---|---|---|
| Gnani | `POST api.vachana.ai/api/v1/tts/inference`, model `timbre-v3.0`, voice Shivani, hi-IN | HTTP 200, 81,964 bytes of WAV |
| Gnani | `POST api.vachana.ai/stt/v3` on that audio, hi-IN | HTTP 200, non-empty transcript |
| DeepSeek | `POST api.deepseek.com/chat/completions`, `max_tokens 8` | HTTP 200, requested `deepseek-flash`, served `deepseek-flash` |
| Gemini | not called | optional: owner decision 2026-10-28 (CHANGELOG.md): "Gemini, Google Cloud speech and Azure speech keys will not be provided"; DeepSeek is the default LLM (owner decision, CHANGELOG), so the "Gemini key" and "Gemini model ID pinned" parts of H-01 are waived, not met |

## Earlier evidence (not re-run)
- VOICE-01 (`proof/VOICE-01/proof.md`, signed `verified.md` 2026-10-23): Timbre v3.0 TTS to REST STT round trips for kn-IN and hi-IN, stream STT, batch STT; the verifier repeated it live.
- LIVE-ACCEPT (`proof/LIVE-ACCEPT/proof.md`, `verified.md`): live DeepSeek judge scoring and Gnani calls in the HubSpot acceptance run. It also records that Gnani **batch** STT with diarization failed server-side in that session (jobs ended FAILED with no reason); the REST and TTS paths above worked.
- `proof/QA-RC/verifier/live_deepseek.txt`, `live_smoke.txt`: verifier's one DeepSeek JSON call (`deepseek-flash`) and one kn-IN round trip.
- `SECRET_KEY`: `scripts/demo.sh` generates it when empty; the stack in this session started with a generated one and the integrations worker (which fails fast without it, FIX-01) stayed up.

## Caveats
- Gnani allows one concurrent request per key; other sessions share the key, so 429s are possible. None occurred in this run (`gnani_http` shows only 200s).
- This proves the keys work on 2026-10-30; it does not prove the owner placed them in their own `.env` (the session received them as environment variables).
