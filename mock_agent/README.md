# Mock EMI agent (VOICE-03)

Synthetic "Suraksha Finance" collections agent speaking `pareeksha-audio-v1` (PCM s16le 16 kHz,
20 ms frames, JSON `start`/`stop`/`transcript`/`tool_call`/`call_end`). It always sends glass-box
messages. STT/TTS go through `pareeksha.gnani` (needs `GNANI_API_KEY`); the dialog is scripted, so no
LLM is used. `GET /health` serves the compose healthcheck; any other path is a call socket.

Run: `python -m mock_agent.server` (port `MOCK_AGENT_PORT`, default 8765).

Planted bugs (FR-MK-3), toggled with `MOCK_BUGS=a,b` or per call with `start.metadata.mock_bugs`:

| `MOCK_BUGS` name | Behaviour |
|---|---|
| `no_disclosure` | skips the recording disclosure in the opening turn |
| `no_amount_confirm` | never restates/confirms the EMI amount before closing |
| `english_to_kannada` | replies in English when the caller speaks Kannada |
| `ignore_interrupt` | VAD off while talking: barge-in is never heard |
| `false_waiver` | promises to waive the late fee (no authority, no tool call) |
