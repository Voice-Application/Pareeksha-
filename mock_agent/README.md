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

## Clean behaviour (bugs off), FIX-02

The scripted dialog answers what the caller actually said instead of walking a fixed script: it never records a
promise the caller did not make (a date is extracted first, read back with the amount, and only then recorded with the
caller's own date), answers loan-ID / amount / due-date / "are you a bot" questions, transfers on a request for a human
(`transfer_to_human`), asks for the UTR when the caller says they already paid, declines waivers (escalating once, never
promising), stays calm with abuse, redirects off-topic talk, checks the caller is still there on silence, says the
recording disclosure again when the caller talked over it, and varies its wording so it never loops. Each repeated
intent gets a different answer and ends in a handoff or goodbye instead of a loop. A Gnani 429 on STT is retried.
