# 3. Scenarios  `/scenarios`, `/scenarios/[id]`

Requirements: FR-SC-1 (Must), FR-SC-2 generate (Must per requirements; SCOPE keeps `generator` in API-05, Day 4), FR-SC-3, FR-SC-4. Purpose: author and review what the synthetic caller is trying to do. Scenarios are language-independent; the persona decides language.

## List

```
EYEBROW 18 scenarios for EMI Reminder Bot
TITLE   Scenarios                                  [Generate with AI] [New scenario]
[search] [Agent v] [Source v: manual|generated|promoted] [Tags v]
+-- DataTable ------------------------------------------------------------------+
| Title                          Source     Tags                 Max turns  Used in |
| Already paid, wants confirm.   manual     payment_dispute ...  12         3 runs  |
| Promoted: wrong amount (call)  promoted   asr  -> call #17     12         1 test  |
+-------------------------------------------------------------------------------+
```
`source` renders as a neutral chip; `promoted` rows show a link to the source call. Row menu: Edit, Duplicate, Delete (refused with an explanation if used by a run, per API 409).

## Editor (`/scenarios/[id]`, and "New scenario" opens the same page)
Two columns: form left, `SamplePanel` right (sticky).

Form sections:
1. **Goal:** title; agent (select); caller goal (textarea, hint "Write what the caller wants, in English. The persona decides the language").
2. **Facts the caller knows:** fixtures as a key-value list (name, loan id, amount, utr); reveal rules (textarea, hint "When may the caller share each fact?").
3. **What good looks like:** success criteria (textarea); must-say and must-not-say (tag lists); expected tool calls (ordered list of tool names from the agent's declared tools, with a "required order" switch).
4. **Limits and labels:** max turns (number), tags (tag input with suggestions `happy_path, edge_case, adversarial, payment_dispute`).

Right `SamplePanel`: a read-only "how the judge will read this" summary: success criteria rendered as a checklist, the fixtures table, and a warning list (see below). No fake caller preview; previews of audio belong to personas.

Non-blocking authoring warnings (amber, inline in `SamplePanel`): success criteria shorter than 20 characters; no must-not-say; caller goal mentions a fact absent from fixtures.

## Generate with AI (Sheet)
Step 1: pick agent, count (1-20), mix sliders (happy path, edge case, adversarial) that always sum to the count; button `Generate`. Step 2 (after the 202): progress state "Generating 10 scenarios" polling the draft until `ready`. Step 3 review: a list of drafts, each a compact card with title, goal, success criteria, tags and a checkbox (default on); inline edit via `Edit` opens the editor in a nested Dialog; footer `Save 8 selected`. Drafts are not saved until this footer is used; closing the Sheet with unsaved drafts asks to confirm.

## Components
`DataTable`, `FilterBar`, `PageHeader`, form primitives, `KeyValueList`, tag input, `SamplePanel`, `Sheet`, `DraftReviewList` (checkbox cards), `ConfirmDialog`.

## Data
`GET/POST/PATCH/DELETE /scenarios`, `POST /agents/{id}/scenarios:generate`, `GET /scenario-drafts/{id}`, `POST /scenarios:bulk`. The list's "Used in" count: gap G-5 (derive from runs client-side is not feasible; show dash if absent).

## States
- **Empty:** "No scenarios yet. A scenario tells the synthetic caller what to try." Primary `New scenario`, secondary `Generate with AI`.
- **Filtered empty:** standard.
- **Loading:** 6 skeleton rows; editor: four section skeletons.
- **Error:** standard; delete refused (409) shows a Dialog listing the run names that use it with links.
- **Generate states:** idle; generating (skeleton cards x count, cancel link); partial (API returns fewer valid drafts than asked: strip "7 of 10 drafts passed validation. 3 were discarded." with the reasons in a disclosure); failed (strip with error and `Try again`, count preserved); ready.
- **Validation:** required fields (title, goal, success criteria) flagged on blur and on save; max turns between 2 and 40.
- **Promoted scenarios:** editor shows a banner "Promoted from call #17" with a link; goal text may be edited but the link stays.
