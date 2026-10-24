# 1. Overview  `/`

Requirement: FR-DB-1 (Must). Purpose: in five seconds, answer "is my agent okay, and is the platform healthy?", then send the user to the worst thing. Not a vanity dashboard: every number links to the list or call behind it.

## Layout

```
EYEBROW  Mock EMI agent  [agent switcher v]
TITLE    Latest run passed 8 of 12 calls, 2 critical            [New run]
         Run "Prompt v3 baseline" finished 14 min ago. 3 calls need human review.

+-- StatTile row (4) ---------------------------------------------------------------+
| Pass rate (last run) | Critical failures | Open DLQ items | Credits used / budget |
+-------------------------------------------------------------------------------+
+-- Panel: Worst cells, last run ---------------+ +-- Panel: Platform health -----------+
| rows: scenario x persona x line, score chip,  | | consumer lag per stage, outbox       |
| top failure tag, link to call                 | | backlog, Kafka/DB status              |
+-----------------------------------------------+ +--------------------------------------+
+-- Panel: Recent runs (5 rows) ----------------+ +-- Panel: Needs human review (5) ------+
| name, agent, status, pass rate, when          | | calls flagged, reason chips, link      |
+-----------------------------------------------+ +--------------------------------------+
```

Different panels have different structure on purpose: tiles, ranked list, key-value health, table. No equal card grid.

## Components
`PageHeader` with agent switcher (Select), `StatTile` x4, `Panel` x4, `DataTable` (compact, no header row for "Worst cells"), `ScoreChip`, `TagChip`, `StatusPill`, `FlagChip`, `Meter` (credits), key-value health list with `StatusDot`.

## Data
`GET /runs?agent_id=` (latest + 5 recent), `GET /runs/{id}` summary and `GET /runs/{id}/items` (worst cells = lowest `overall_score` first, top 5), `GET /metrics/summary` (lag, outbox_backlog, dlq_open, credits_used), `GET /usage` (remaining budget). Needs-review list: see gap G-2 in `00-shared.md` section 11.

## Interactions
- Agent switcher persists in the URL (`?agent=`) and in local storage as a convenience only.
- Tiles link: pass rate to the run, critical failures to the run with `?filter=critical`, DLQ to `/dlq`, credits to a `Meter` tooltip (no page in v1).
- Health rows turn amber when lag is above 20 or backlog above 0 for more than 30 s; red when `kafka` is not `ok`.
- Polls `GET /metrics/summary` every 15 s; run panels refetch on window focus.

## States
- **Empty (no agent):** page title "Add your first agent", one sentence, primary `Add agent`, secondary link "Use the demo agent" only if the seed created it. Tiles and panels are not drawn.
- **Empty (agent but no runs):** title "No runs yet for this agent". Tiles show dashes. Worst cells and Recent runs replaced by one EmptyState: "A run sends synthetic callers to your agent." + `Create run`. Health panel still renders.
- **Loading:** four tile skeletons (value bar 64px) and four panel skeletons with 5 rows each.
- **Error:** per-panel `ErrorPanel` (panels load independently). If `GET /runs` fails the header shows a neutral title "Overview" and an inline error.
- **Run in progress:** header title becomes "Run is 7 of 12 done" with `LiveIndicator`; tiles show provisional values with a "so far" caption; link "Watch live" to the run.
- **Stale health:** if `/metrics/summary` has not updated for 45 s, the health panel shows "Last updated 1 min ago" in amber.
