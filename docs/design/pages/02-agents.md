# 2. Agents  `/agents`, `/agents/new`, `/agents/[id]`

Requirements: FR-AG-1..4 (Must; glass-box Should), FR-DX-7. Purpose: register the voice bot under test and prove the platform can reach it.

## List `/agents`

```
EYEBROW 3 active, 1 archived
TITLE   Agents                                                   [Add agent]
[search] [Adapter v] [Language v] [Show archived  o]
+-- DataTable ----------------------------------------------------------------+
| Name              Adapter    Languages   Glass-box  Last run      Connection |
| EMI Reminder Bot  audio_v1   kn hi en    yes        14 min ago    ok 820 ms  |
+-----------------------------------------------------------------------------+
```
Columns: name (link, with a `demo` chip when seeded), adapter (mono), languages (mono codes), glass-box (check icon or dash), last run (relative, link), connection (last test result: check + first audio ms, cross + error word, or dash "never tested"). Row menu: Edit, Test connection, Archive.

## Create and edit (`/agents/new`, `/agents/[id]`)
Full page, not a Sheet, because the form is long. Two-column: form sections left (680px), sticky "Test connection" panel right (408px).

Sections (each a Panel, collapsible once valid):
1. **Basics:** name, description (the prompt text, textarea with line count), languages (multiselect `kn-IN, hi-IN, en-IN`).
2. **Connection:** adapter (segmented: `audio_v1`, `pipecat`, `livekit`, `vapi`; unsupported-in-this-build options disabled with a tooltip), endpoint URL (mono), adapter config (key-value list or JSON), glass-box switch, max call seconds.
3. **Rules the judge checks:** mandatory disclosures (repeater rows: id, text, regex, within turns), forbidden phrases (id, text, regex), expected tools (name, description), bias list (tag input).
4. **Danger zone** (edit only): Archive agent (ConfirmDialog; text explains archived agents disappear from run creation but keep history).

Right panel `ConnectionTest`: button `Test connection`; result region shows progress ("Opening socket", "Sending 1 s of silence", "Waiting for agent audio, up to 10 s") then either a pass strip (`ok`, first audio 820 ms, protocol, glass-box messages seen yes/no) or a fail strip with the API `error` word (`dns`, `refused`, `timeout`, `protocol`) and the `detail` string, plus one suggested fix per error word from a fixed dictionary. The test needs a saved agent; on `/agents/new` the button is disabled with "Save the agent first", and the Save button's secondary action is `Save and test`.

Regex fields show a live preview: a mono input "try a phrase" and a match/no-match indicator.

## Components
`DataTable`, `FilterBar`, `PageHeader`, `Panel`, form primitives, repeater rows (`KeyValueList`), `SegmentedControl`, `ConnectionTest`, `ConfirmDialog`, `StatusPill` (connection), `Button`.

## Data
`GET /agents`, `GET /agents/{id}`, `POST /agents`, `PATCH /agents/{id}`, `POST /agents/{id}/archive`, `POST /agents/{id}/test-connection`. Last-run column from `GET /runs?agent_id=` (first row); last connection result: gap G-4 (not in the agent object; fall back to dash).

## States
- **Empty list:** EmptyState "No agents yet. An agent is the voice bot you want to test." Primary `Add agent`; secondary text "Run `make demo` to create a mock agent with planted bugs" (docs link).
- **Filtered empty:** "No agents match these filters." + Clear.
- **Loading:** 5 skeleton rows. Edit page: three section skeletons.
- **List error / 404:** standard (shared 5.3). An archived agent opens read-only with a banner "Archived on {date}. Restore" (Restore only if API supports; otherwise banner without action).
- **Validation:** inline field errors; regex that does not compile shows "This pattern is not valid: {message}"; duplicate disclosure ids flagged on the repeater row.
- **Test connection states:** idle, running (indeterminate bar, button disabled, can be cancelled), passed, failed, timed out (after 10 s the API returns timeout; UI shows it as failed with "no audio within 10000 ms"). Result is kept until the form is edited, then marked "Result is for the previous settings".
- **Unsaved changes:** leaving the edit page with changes asks for confirmation.
