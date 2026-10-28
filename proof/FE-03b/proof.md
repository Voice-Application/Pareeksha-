# FE-03b proof: Run compare page (`/runs/compare?base=&head=`)

Branch `task/FE-03b` (from origin/claude/amazing-einstein-agkccc). FE-03 was rejected only because this page was a `STUB(FE-03)` (proof/FE-03/rejected.md); the stub is replaced by the real page.

## Built
- `web/app/runs/compare/page.tsx` (Suspense wrapper), `web/components/runs/run-compare.tsx`, `web/components/runs/compare-diff.ts` (pure helpers).
- Two run pickers (native selects: name, date, pass rate; typing jumps to an option), Swap, URL is the state. Missing parameters: "Choose two runs to compare" + Compare button.
- Header: base to head eyebrow, sentence title from `GET /runs/compare` summary ("4 cells regressed, 0 improved, 0 unchanged" / "No differences" / "No overlapping cells"), pass-rate sentence, newly failing cell named, Open head run.
- Four delta tiles (pass rate, critical, mean score, latency p95) from the two run summaries: signed value, arrow, check/cross icon, direction stated in words ("down 50 points, worse").
- Changed cells table (newly failing, regressed by delta, improved; unchanged and not-comparable collapsed in closed `details`), diverging 64 px delta bar plus signed number, Base call / Head call links (call ids from `GET /runs/{id}/items`).
- Diff heatmap: head score, signed delta lower-left, 2 px outline on newly failing, unchanged cells at 45% with full-strength text, arrow-key navigation, cells link to the head call.
- Per-dimension deltas, computed client-side: mean 0-4 score of each rubric dimension across each run's evaluations (`GET /calls/{id}`, first 60 evaluated calls per run). No API or contract change.
- Agent panel: if the runs used different agents, added/removed lines (plus/minus icons) for description, disclosures, forbidden phrases, tools from `GET /agents/{id}` (current config). If the same agent: says plainly that per-run config snapshots are not exposed (gap G-8), it does not claim the config was identical.
- States: loading skeletons, 404 run (PageError naming the cause), compare failure (ErrorPanel + Retry while tiles stay), same run notice, different-agents strip, base/head still running banner with 5 s polling, no overlap EmptyState, no change.
- No `STUB`/`TODO`/`FIXME` anywhere in web/ (grep clean).

## Real data
Stack: private compose project `fe03b`, ports 62800/62432/62094/62765, proxy overlay per proof/INFRA-01 (`docker-compose.proxy.yml`), full worker set (planner, simulator, evaluator, finalizer, ...), `python -m pareeksha.seed`.
Two real runs of "EMI Reminder Bot" (2 scenarios x 2 personas x clean_16k = 4 calls each), real Gnani TTS/STT and DeepSeek caller/judge, `max_concurrency: 1`:
- `Prompt v2 baseline` `62f28756-1dcf-47c3-b49d-6c755173f602`: clean mock agent, pass 50%, mean 85.0 (`run_base.json`)
- `Prompt v3 candidate (planted bugs)` `d1d39879-9f24-4152-aa64-fb649c3aad27`: mock agent with `MOCK_BUGS=no_amount_confirm,no_disclosure`, pass 0%, 2 critical, mean 41.25 (`run_head.json`)
Spend: `credit_use.md` (59 TTS, 44 STT, 8 judge calls).

## Reproduce
```
export BUILDX_BAKE_ENTITLEMENTS_FS=0 CA_BUNDLE=/root/.ccr/ca-bundle.crt
DC="docker compose -p fe03b -f docker-compose.yml -f docker-compose.proxy.yml"   # .env from .env.example with keys, API_HOST_PORT=62800 etc.
$DC --profile workers up -d --build postgres kafka kafka-init migrate api outbox-relay planner simulator evaluator finalizer reconciler dlq-recorder retrier mock-agent
$DC run --rm --no-deps api python -m pareeksha.seed
# run 1 (clean), then MOCK_BUGS=no_amount_confirm,no_disclosure $DC up -d --no-deps mock-agent, run 2 via scripts/verify/vapi.py run_and_wait (2 scenarios x 2 personas x clean_16k)
cd web && npm run build && PAREEKSHA_API_URL=http://127.0.0.1:62800/api/v1 PAREEKSHA_API_KEY=<key> npx next start -p 3100 -H 127.0.0.1
node scripts/shots.mjs ../proof/FE-03b/screenshots "/runs/compare?base=<base>&head=<head>=compare" "/runs/compare=compare-empty"
node scripts/axe-real.mjs ../proof/FE-03b/axe_real.json "/runs/compare?base=<base>&head=<head>"
REAL_WEB_URL=http://127.0.0.1:3100 REAL_API_URL=http://127.0.0.1:62800/api/v1 npx playwright test -c playwright.real.config.ts tests/real/compare.spec.ts
npm run lint && npm run typecheck && npm run build && npx playwright test
```

## Results
- Mock suite `playwright.log`: **196 passed, 0 failed, 0 skipped** (186 existing + 10 new in `tests/fe03b-compare.spec.ts`: choose-two flow, summary/ordering/words/links with axe in light and dark, heatmap arrow keys, swap and pickers, different agents, same run, running head, no overlap and no differences, compare failure + retry + 404, loading).
- Real-stack spec `playwright_real.log`: 1 passed (`tests/real/compare.spec.ts`: title equals the server summary, 7 dimension rows, grid, axe, no console errors or 5xx).
- `axe_real.json`: wcag2a+wcag2aa on the real pages, light and dark, 6 page-themes, **0 violations**.
- `lint.log` exit 0, `typecheck.log` exit 0, `build.log` exit 0.
- `screenshots/`: compare (4 regressions), compare-swapped (4 improvements), compare-same-run, compare-empty (choose two runs), each light and dark. `ui_review.md`: self-review.

## Notes
- Agent config snapshot per run (gap G-8) is not in the API; the panel only diffs current configs of different agents and says so for same-agent runs.
- Latency p95 is "not measured" on these real runs (no per-turn timing reported), and the tile says so.
- Running the existing screens spec rewrites screenshots under proof/FE-02, FE-05; those were reverted, not part of this change.
