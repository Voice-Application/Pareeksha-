# 15. DLQ  `/dlq`

Requirements: FR-IN-10, FR-RN-9, F29 (Should), NFR-4. Purpose: show events that failed three times, so an operator can see why and replay or discard them. A healthy system shows an empty page, and that must feel good rather than broken.

## Layout

```
EYEBROW  1 open, 4 replayed, 0 discarded
TITLE    1 event is waiting in the dead-letter queue                  [Replay all open]
         Failed after 3 attempts on evaluator. Replaying re-publishes it from the start.
[Status v: open|replayed|discarded] [Topic v] [Consumer v] [Date v]
+-- DataTable -------------------------------------------------------------------------------+
| Failed        Original topic               Consumer     Error                    Attempts    |
| 3 min ago     pareeksha.call.completed.v1  evaluator    JudgeSchemaError: ...     3  [v]      |
+--------------------------------------------------------------------------------------+
(row expanded or Sheet 560px)
  Error (full, mono, wrap)   Envelope JSON (CodeBlock, collapsible, PII masked as received)
  [Replay]  [Discard]  [Copy event id]
```
- Title states the number of open items; zero open: "The dead-letter queue is empty" in neutral teal text with a check icon.
- Error column shows the first 80 characters; the full text is in the Sheet. Mono for topic and consumer.
- `Replay` (primary in the row Sheet) calls replay; the item moves to `replayed` and a Toast says "Replayed. It will be processed again with attempt 1." `Discard` is destructive-outlined with a ConfirmDialog that requires reading: "Discard permanently? The event will not be processed."
- `Replay all open` shows a ConfirmDialog with the count and the topics; processed serially with progress; partial failure result lists failures.
- Replayed items show the replay time and a link to the consumer outcome if known (call or evaluation id from the envelope payload).
- Sidebar count shows open items; same number in Overview health panel.

## Components
`PageHeader`, `FilterBar`, `DataTable`, `StatusPill` (open: fail-tinted neutral with cross; replayed: neutral check; discarded: neutral dash), `Sheet`, `CodeBlock` (JSON, copy), `ConfirmDialog`, `Toast`.

## Data
`GET /dlq?status=open`, `POST /dlq/{id}/replay`, `POST /dlq/{id}/discard`. Aggregate count also in `GET /metrics/summary` (`dlq_open`). Needs `admin` or operator scope per API keys (the UI hides action buttons for keys without it and says why in a tooltip).

## States
- **Empty (healthy):** "The dead-letter queue is empty. Events that fail three times will appear here." with a check icon; no CTA. In the filtered `replayed` or `discarded` view with none: standard filtered empty.
- **Loading:** 4 skeleton rows.
- **Error:** list standard. Replay failure (409 already replayed, 5xx): Toast with reason, row unchanged. Bulk replay partial failure: Dialog with per-item results.
- **Polling:** the list refetches every 15 s and on focus; new rows slide in without moving the focused row.
- **Large envelopes:** JSON beyond 20 KB is truncated with `Show all`.
- **Scope missing:** page readable with `read`; Replay and Discard disabled with "Needs the admin scope".
