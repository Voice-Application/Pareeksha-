# 5. Noise profiles  `/noise-profiles`, `/noise-profiles/[id]`

Requirements: FR-NP-1, FR-NP-2 (Must). Purpose: define the phone line the caller is on: codec, band-limit, background, SNR, packet loss. Eight named profiles ship (`clean_16k` ... `auto_rickshaw_0db`).

## List

```
EYEBROW 8 profiles
TITLE   Noise profiles                                         [New profile]
+-- DataTable --------------------------------------------------------------------+
| Name                     Represents          Rate  Codec  Background    SNR   Loss  Preview |
| pstn_market_5db          Vegetable market    8 kHz A-law  market_crowd  5 dB  0%    > play  |
+---------------------------------------------------------------------------------+
```
SNR cell contains a mono value and a 48px bar (neutral ink) to make harsh lines visible at a glance. Rows sorted by SNR descending by default so the list reads from clean to hostile. `clip` and `loss` shown as small icon-chips only when on.

## Editor (Sheet)
Fields: name (mono, slug validation), represents (free text, optional), sample rate (segmented 8 kHz, 16 kHz), codec (segmented none, mulaw, alaw; helper text "India's landline network uses A-law."), PSTN bandpass (switch), background category (select), SNR dB (slider 0-30 with mono value, disabled when background is none), packet loss % (slider 0-10), clipping (switch).

`PreviewBar`: two modes, segmented. "Sample clip" plays the default sample degraded with the current values. "My clip" accepts a file (WAV/MP3) via `FileDropzone`, up to 10 MB. Plays original and degraded back to back with A/B toggle (buttons `Original`, `Processed`) and a small spectrum strip showing the band-limit (flat line, 1.5px, no gradient).

## Components
`DataTable`, `Sheet`, form primitives, slider, `SegmentedControl`, `PreviewBar`, `AudioTransport`, `FileDropzone`, `ConfirmDialog`.

## Data
`GET/POST/PATCH/DELETE /noise-profiles`, `POST /noise-profiles/{id}/preview` (multipart `file` optional). Unsaved preview: same gap as personas (G-6).

## States
- **Empty:** only if seed was skipped: "No noise profiles. Seed the eight built-in lines with `make demo`, or create one." Primary `New profile`.
- **Loading:** skeleton rows; preview shows spinner on the button and keeps previous audio until new audio is ready.
- **Error:** list standard; preview failure inline in `PreviewBar` with Retry; file too large or wrong type: field error "Use a WAV or MP3 under 10 MB."; delete refused (409): lists referencing runs.
- **Validation:** name unique; 16 kHz with a PSTN bandpass is allowed but warned ("Phone lines are 8 kHz. This profile will sound unrealistic.").
- **Seed profiles** are editable but show `seed` chip and "Reset to default" in the row menu (Could).
