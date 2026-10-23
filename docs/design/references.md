# Design references (DES-01)

Collected 23 Oct 2026 from public pages. Each entry says what we take and what we leave. Products that sit behind a login (Hamming, Cekura, Datadog, Sentry app screens) were judged from their public docs, blog posts and marketing screenshots, not from a live account; treat those as indirect.

| # | Reference | Link | Take this | Leave this |
|---|---|---|---|---|
| 1 | **Linear** UI redesign write-up (Mar 2024) | https://linear.app/now/how-we-redesigned-the-linear-ui | Theme built from three inputs (base, accent, contrast) in a perceptual space (LCH), surfaces separated by tiny lightness steps and hairlines instead of shadows, dense navigation with reduced visual noise, a high-contrast mode comes free. | The signature lavender-blue accent and the near-black-only marketing mood. |
| 2 | **Vercel Geist** colour system | https://vercel.com/geist/colors | Ten-step semantic scale (component bg 1-3, borders 4-6, solid 7-8, text 9-10), "draw each border once", translucent shadows only, two background levels. We copy the *structure* of our neutral tokens from this. | Pure white/black neutrals; we go warm. |
| 3 | **Geist** typeface (Sans + Mono, open source, on Google Fonts) | https://fonts.google.com/specimen/Geist | A developer-grade sans with a matching mono that has tabular figures; free; variable. We use it for UI and numbers. | n/a (Geist has no Kannada or Devanagari, so we pair Noto Sans Kannada and Noto Sans Devanagari for transcript text). |
| 4 | **Datadog** APM trace view (Flame graph, Span list, Waterfall) | https://docs.datadoghq.com/tracing/trace_explorer/trace_view/ | One shared time axis with a minimap, a row per span with relative bar plus absolute ms, a legend that groups by one dimension, errors highlighted on demand. This is our call timeline: one row per speaker on one shared time axis. | Multi-colour categorical flame graph palette; colour in our UI means score, not category. |
| 5 | **PostHog** session replay | https://posthog.com/session-replay | Player on one side, event timeline beside it, click an event to seek, filter the timeline by type. Maps 1:1 to "click an evidence turn, audio seeks". | Playful brand illustration and heavy yellow accent. |
| 6 | **Sentry** issue and trace pages | https://sentry.io/ (product tour: agent tracing, trace waterfall) | Issue-first framing: a failure has a title, a count, tags, and the offending span highlighted. Maps to failure-type tags with the evidence turn. | Purple brand colour, marketing gradients. |
| 7 | **Cekura** voice observability | https://www.cekura.ai/blogs/voice-observability | The domain model users already know: audio, STT, LLM reasoning, tool calls, TTS and outcome shown in one trace; "why did this conversation fail" as the page's job. Validates that call detail is the hero screen. | Their generic SaaS dashboard chrome. |
| 8 | **Hamming** post-call analytics and QA framework | https://hamming.ai/resources/post-call-analytics-voice-agents-metrics-monitoring | Metrics grouped by what the QA lead asks (outcomes, latency, conversation), p50/p95 shown together, "dashboard says 98% but customers still call back" argument: surface the failing turn, not the average. | Averages-first overview pages. |
| 9 | **Raycast** | https://www.raycast.com/ | Restraint, keyboard-first density, small radii, one calm surface hierarchy. Keyboard shortcuts shown inline as keycaps. | Red brand gradient and decorative hero art. |
| 10 | **Godly**, **Land-book** (galleries), **Dribbble** waveform / voice-transcript shots | https://godly.website/ , https://land-book.com/ , https://dribbble.com/tags/waveform , https://dribbble.com/shots/27801469-AI-Voice-Recorder-App-UI-UX-Design-Live-Transcription-Audio | Used as a check on what to avoid: most voice shots are glow-on-black, rounded-pill, gradient waveform art. The shared positive take-away: waveform and live transcript belong on the same vertical axis, with the current line visibly anchored to the playhead. | Gradient waveforms, glow, glassmorphism, oversized rounded cards. |
| 11 | **Okabe-Ito** and **Paul Tol** colour-blind-safe schemes | https://sronpersonalpages.nl/~pault/ , https://conceptviz.app/blog/okabe-ito-palette-hex-codes-complete-reference | Bluish green / orange / vermillion as the safe pass / warn / fail triple, and "separate by lightness as well as hue". Our score scale is checked against Machado CVD simulation (see `proof/DES-01/validate_palette.py`). | n/a |

## Patterns we are adopting across the product

1. **Panels separated by hairlines and small lightness steps, not shadows** (Linear, Geist).
2. **One shared time axis** for audio, speakers, latency and failures (Datadog trace view).
3. **List/detail with seek-on-click** (PostHog replay): every evidence reference is a button that moves the playhead.
4. **Issue-first failure presentation** (Sentry): a failure has a type tag, the offending turn, and the reason.
5. **Numbers in mono with tabular figures**, everything else in a quiet sans (Geist).
6. **Colour is meaning**: the only saturated colours are the score scale and one interaction accent.
