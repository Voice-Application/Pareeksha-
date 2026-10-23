# 4. Personas  `/personas`, `/personas/[id]`

Requirements: FR-PE-1, FR-PE-2 (Must), FR-PE-3 preview (Should). Purpose: define who is calling: language, code-mix, voice, mood and habits. 20 seeds ship; users add their own.

## List

```
EYEBROW 20 personas: 7 Kannada, 6 Hindi, 4 English, 3 behaviour
TITLE   Personas                                                [New persona]
[search] [Language v] [Code-mix v] [Emotion v] [Interrupts v]
+-- DataTable ------------------------------------------------------------------+
| > Name                          Lang   Mix    Emotion      Speed Interrupts Voice   |
| > Manju, frustrated Kanglish    kn-IN  heavy  frustrated   1.1x  ||| 2     Prakash |
+------------------------------------------------------------------------------+
```
First column has a 28px play button that plays the preview line (cached audio) in place; only one plays at a time. Interrupt level shown as 0-3 pips in neutral ink (not score colours). Seed rows carry a `seed` chip.

## Editor (Sheet 480px from the list; full page `/personas/[id]` for deep links)
Fields in the order of FR-PE-1, grouped:
1. **Who:** name, language (select), code-mix style (segmented: none, light, heavy), dialect label (text; helper "Descriptive only. We do not claim the voice is that dialect.").
2. **Voice:** TTS model (select, default `timbre-v3.0`), voice id (select of the 13 Timbre voices with a play button per option), speed (slider 0.8 to 1.3 with mono value), emotion (select).
3. **Behaviour:** patience (turns, number), interruption level (segmented 0-3, each with a one-line description: never, rarely, often, constantly), silence habit (select), behaviour notes (textarea).

`PreviewBar` pinned to the bottom of the Sheet: `Play sample line` (calls preview with the current unsaved values), shows duration and cost note ("uses Gnani TTS credits; cached lines are free"). Cache hits show "from cache".

Guardrail copy under voice: "Voices are Gnani stock voices. Do not use a real person's voice." (R7).

## Components
`DataTable`, `FilterBar`, `Sheet`, form primitives, slider, `SegmentedControl`, `PreviewBar` (uses `AudioTransport` in its compact form), `ConfirmDialog`.

## Data
`GET/POST/PATCH/DELETE /personas`, `POST /personas/{id}/preview` (audio/wav). Unsaved preview needs a way to preview without saving: gap G-6 (design assumes `POST /personas:preview` with a body; otherwise the Play button is disabled until saved).

## States
- **Empty:** only possible if the seed was not run: "No personas yet. Seed the 20 built-in personas with `make demo`, or create your own." Primary `New persona`.
- **Filtered empty:** standard.
- **Loading:** skeleton rows; preview button shows spinner and a 14px skeleton waveform while synthesising.
- **Error:** list standard. Preview failure (TTS error, 429/credits): inline in `PreviewBar`: "Could not synthesise: {reason}" with Retry; the form stays editable. Delete refused (409): Dialog listing runs that use it.
- **Validation:** duplicate voice for the same language is allowed but triggers a warning chip ("Same voice as Priya, hi-IN"). Speed out of range blocked.
- **Behaviour personas** (elderly-slow, interrupter, silent, abusive-but-safe, confused) show a small label chip "behaviour" so they can be filtered.
