# 16. Calibration  `/calibration`

Requirements: FR-EV-7, FR-EV-8 (Should), PRD §8 (kappa and Spearman published, EVAL-06). Purpose: show how far the automatic judge can be trusted, by comparing it with the owner's own labels, and give a fast way to label calls blind.

## Layout

```
EYEBROW  Rubric rubric-2026-10-v1 [version v]
TITLE    The judge agrees with your labels on pass or fail in 24 of 32 calls (kappa 0.71)
         Overall scores correlate at rho 0.78. Largest gap: task_completion (MAE 0.4).
+- StatTile x4 -----------------------------------------------------------------------+
| Kappa pass/fail 0.71 [target >= 0.6 check] | Spearman 0.78 | Labelled calls 32/30 | Judge-only disagreements 8 |
+------------------------------------------------------------------------------------+
+-- Panel: Per-dimension error (bar list) ----------+ +-- Panel: Label queue ---------------------+
| 7 rows: name, MAE bar (0-4 scale), n               | | Blind labelling: next call to label,     |
| ordered by largest error                           | | progress 32 of 30+, [Start labelling]    |
+----------------------------------------------------+ +------------------------------------------+
+-- Panel: Disagreements (DataTable) --------------------------------------------------------------+
| Call  Judge verdict  Your verdict  Judge score  Your score  Biggest dimension gap  Link          |
+--------------------------------------------------------------------------------------------------+
```
- Title written from the numbers: agree count out of n, kappa. If kappa is below the 0.6 target (PRD §8) the supporting sentence says "Below the 0.6 target. The rubric should be revised and re-calibrated." with the exact wording from the plan, and the kappa tile gets the cross icon; at or above, check icon. The threshold appears as a dashed line in the tile mini-meter.
- Rubric version selector re-queries; changing version shows that version's numbers only.
- `MAE bars`: horizontal bars on a 0-4 axis, fill `--series-1`, value in mono; the largest bar is not coloured differently, it is just first.
- **Label queue and blind labelling:** `Start labelling` opens `/calls/{id}?blind=1` for the next unreviewed call in a restricted mode of Call detail: judge scores, verdict and summary are hidden (replaced by a neutral "Hidden until you save" panel), transcript and audio are available, and the review Sheet is open. After `Save review` it reveals the judge result for 3 seconds in the panel, then offers `Next call`. This keeps labels independent of the judge (PRD blind labelling). Order is randomised server-side if available, else by id hash.
- **Disagreements table:** rows where pass/fail differs or any dimension differs by 2 or more. Click opens the call with both judgements side by side in the Verdict panel.

## Components
`PageHeader`, version `Select`, `StatTile` (with target meter), `BarList`, `Panel`, `DataTable`, `Button`, restricted mode of `CallDetail` (`blind` prop hides Verdict, Dimension scores, Failure tags, Checks result words stay visible because they are deterministic facts).

## Data
`GET /calibration?rubric_version=` (`n`, `kappa_pass_fail`, `spearman_overall`, `dimension_mae`), `POST /calls/{id}/review`. Label queue and disagreement list: gap G-13 (needs the list of evaluations with human review, and the next unlabelled call).

## States
- **Empty (no human labels):** "No labelled calls yet. Label calls blind, then the platform compares your scores with the judge." Primary `Start labelling` (disabled with reason when no evaluated calls exist: "Run a few calls first", link to `New run`). Tiles show dashes.
- **Too few labels:** with n below 10 the tiles show values but a neutral strip warns "Only {n} labelled calls. Agreement numbers are unreliable below 30." Kappa and Spearman are not coloured.
- **Single class** (all labels pass): kappa is undefined; the API may return null; tile shows dash and tooltip "Needs both passing and failing calls."
- **Loading:** tiles skeleton, bars skeleton, 5 table rows.
- **Error:** standard per panel.
- **Rubric bump:** if the current rubric has no labels but an older one does, a strip suggests the older version and states labels do not carry over.
