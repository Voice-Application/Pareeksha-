# 11. Audits  `/audits`, `/audits/new`

Requirements: FR-AU-1..5, US-6 (Must; promote Should), webhook-imported audits arrive here too (FR-IN-7). Purpose: score real recorded calls with the same rubric as simulations.

## List `/audits`

```
EYEBROW 14 audits, 2 transcribing
TITLE   Audits                                                    [Upload recording]
[search] [Agent v] [Source v: upload|webhook] [Verdict v] [Flag v: needs review] [Date v]
+-- DataTable --------------------------------------------------------------------------+
| File / external id     Agent        Source   Lang   Status         Score  Verdict  Flag  Tags   Uploaded |
| ravi_call_0412.wav     EMI Bot      upload   kn-IN  evaluated      52    fail     flag  2      3 h ago  |
| exotel-CA123           EMI Bot      webhook  kn-IN  transcribing    -      -        -     -      1 min    |
+--------------------------------------------------------------------------------------+
```
- Status uses `StatusPill`: `transcribing`, `evaluating`, `evaluated`, `error`. Rows in progress update every 3 s.
- Source `webhook` rows show the integration name in the cell caption and the masked external id; no phone numbers shown beyond the API's masked values.
- Row opens `/calls/{id}` (audit mode).

## Upload `/audits/new` (page, not a Sheet, because of the file plus options)
Single column, 680px, with a right summary panel:
1. `FileDropzone`: WAV or MP3, up to 10 MB; after drop shows file name, size, duration (read in the browser), a mini waveform, and a `Remove`.
2. Agent (select, required; used as rubric context), language (multiselect `kn-IN, hi-IN, en-IN`; code-mixed calls pick two), switch "Stereo channels are speakers" with helper "Turn on if the agent and caller were recorded on separate channels. Skips diarisation."
3. Consent line (checkbox, required): "I have the right to process this recording and it contains no data I am not allowed to store." (R7). Not pre-checked.
4. `Upload and audit` primary. After `202` navigates to the new call page in `transcribing` state.

Right panel "What happens next": ordered list (Transcribe with speaker separation, find the agent, run the same checks and judge, score). Estimated time "about 1-2 minutes" as static text; cost note when credits tracked.

## Components
`PageHeader`, `FilterBar`, `DataTable`, `StatusPill`, `VerdictBadge`, `FlagChip`, `TagChip` (count), `FileDropzone`, `Waveform` (compact), form primitives, checkbox, `Button`.

## Data
`POST /audits` (multipart), `GET /calls/{id}` for status; list of audits: gap G-10 (`GET /calls?source=upload,webhook` with status, score, flags). Until it exists the list cannot render.

## States
- **Empty:** "No audits yet. Upload a recorded call to score it with the same rubric as your test runs." Primary `Upload recording`; secondary link "Send calls automatically with a webhook" to Integrations.
- **Filtered empty:** standard.
- **Loading:** skeleton rows. Upload: button shows progress "Uploading 4.1 of 6.3 MB" with `ProgressBar`; cancel possible.
- **Error (list):** standard. **Upload errors** (inline, field level): wrong type "Use a WAV or MP3 file"; too large "File is 12.4 MB. The limit is 10 MB."; unreadable audio "We could not read this audio"; 403 scope "Your key cannot upload audits (needs audits:write)"; network failure keeps the form with the file and `Try again`.
- **Row states:** `transcribing` and `evaluating` show a thin indeterminate bar in the Status cell; `error` shows the reason on hover and a `Retry` row action (re-evaluate); an audit where speaker detection was uncertain shows a FlagChip with reason `speakers_unconfirmed` (if provided) and a link "Check speakers".
- **Duplicate webhook delivery:** no row duplication (API dedupes); nothing to show.
