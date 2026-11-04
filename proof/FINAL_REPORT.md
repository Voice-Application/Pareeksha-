# Pareeksha final report

Generated 2026-11-04T11:09:38Z by `scripts/verify/run_all.sh` on commit 504a95af4d885835871ef56fa63e70b76af77054.
Each row is read from its evidence file; "Last run" says whether that step ran on this commit or an earlier one.
PASS only when the evidence file shows the check ran and met its criterion. FAIL = ran and missed (or could not run).
PENDING = needs an input only the owner can provide (HubSpot token, labelled calls, demo video, public repo...); it is not a pass.
NOT RUN = no evidence file; it is not a pass.

| # | GOAL item | Result | Last run | Evidence |
|---|---|---|---|---|
| 1 | Every section-7 task has proof and a signed verified.md | **FAIL** | 2026-11-04T11:09:03Z, re-run on this commit | [proof/verify/V1.md](verify/V1.md) |
| 2 | compose up + make demo gives an evaluated call in < 20 min | **PASS** | not re-run; last run 2026-10-30T15:30:29Z on d9a9974 | [proof/verify/V2.md](verify/V2.md) |
| 3 | 40-call Kafka run, >= 95% free of infra errors; 20-call concurrency-4 timing | **NOT RUN** | no evidence file | none |
| 4 | >= 4 of 5 planted bugs caught with cited turn indices | **PASS** | not re-run; last run 2026-10-30T15:35:24Z on d9a9974 | [proof/verify/V4.md](verify/V4.md) |
| 5 | Webhook-imported real recording audited, HubSpot note within 3 min | **PASS** | not re-run; last run 2026-10-30T15:54:38Z on d9a9974 | [proof/verify/V5.md](verify/V5.md) |
| 6 | Duplicate delivery and worker crash give one evaluation and one CRM note | **PASS** | not re-run; last run 2026-10-30T16:40:26Z on 6ebe99b | [proof/verify/V6.md](verify/V6.md) |
| 7 | Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs | **PASS** | 2026-11-04T11:09:18Z on this commit: recorded evidence re-checked, not re-run | [proof/verify/V7.md](verify/V7.md) |
| 8 | GitHub Action fails a PR enabling a mock bug, passes after the fix | **PASS** | 2026-11-04T11:09:33Z, re-run on this commit | [proof/verify/V8.md](verify/V8.md) |
| 9 | Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6 | **FAIL** | 2026-11-04T11:09:30Z, re-run on this commit | [proof/verify/V9.md](verify/V9.md) |
| 10 | 8 adopter guides followed from a clean clone | **PASS** | 2026-11-04T11:09:17Z on this commit: recorded evidence re-checked, not re-run | [proof/verify/V10.md](verify/V10.md) |
| 11 | Repo public, tagged v1.0.0, demo video + launch post published | **FAIL** | 2026-11-04T11:09:20Z, re-run on this commit | [proof/verify/V11.md](verify/V11.md) |

## V1: Every section-7 task has proof and a signed verified.md: FAIL

STATUS: FAIL
REASON: 2 task(s) without signed proof, 0 build-fail grep hit(s)

## V2: compose up + make demo gives an evaluated call in < 20 min: PASS

STATUS: PASS
REASON: evaluated call in 294s (11 scored evaluations)

## V3: 40-call Kafka run, >= 95% free of infra errors; 20-call concurrency-4 timing: NOT RUN

No proof/verify/V3.md: this step has no evidence from the harness.

## V4: >= 4 of 5 planted bugs caught with cited turn indices: PASS

STATUS: PASS
REASON: control (bugs off) pass rate 2/2; caught 5/5

## V5: Webhook-imported real recording audited, HubSpot note within 3 min: PASS

STATUS: PASS
REASON: HubSpot note created 15.1s after the signed POST

## V6: Duplicate delivery and worker crash give one evaluation and one CRM note: PASS

STATUS: PASS
REASON: one evaluation, no duplicate delivery after replay x2 and SIGKILL

## V7: Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs: PASS

STATUS: PASS
REASON: verifier's DIALECT-02 run meets group, n, CI and consent criteria; recorded run, not re-run here

## V8: GitHub Action fails a PR enabling a mock bug, passes after the fix: PASS

STATUS: PASS
REASON: first run failed, second passed, same workflow, second commit descends

## V9: Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6: FAIL

STATUS: FAIL
REASON: kappa 0.1892 on n = 30  is below the 0.6 target

## V10: 8 adopter guides followed from a clean clone: PASS

STATUS: PASS
REASON: all 8 guide logs end with RESULT: PASS; recorded logs, guides not re-run here

## V11: Repo public, tagged v1.0.0, demo video + launch post published: FAIL

STATUS: FAIL
REASON: release.md has no demo video link (+1 more)

## Notes (records reconciled 2026-11-04)

**Not re-run.** No Gnani, DeepSeek or HubSpot keys were available for this pass, so these rows are not fresh results:
- V2, V4, V5, V6: need the full stack and owner keys. These are the 2026-10-30 results.
- V3: there is no evidence file because the step never finished through the harness. `proof/QA-03/proof.md` records 39/40 calls free of infrastructure errors (97.5%) in run 8422cb13, outside the harness. That does not count as a PASS here.
- V7: the 330 live speech calls were not repeated. The harness applied its criteria to the verifier's own committed run in `proof/DIALECT-02/verifier`, including the `dialect_samples` count that run read from its database. That consent is Vaani's dataset-level consent, not consent the project collected.
- V10: the step only re-read the existing guide logs. The 8 guides were not followed again.

**Rows that pass with a limit.**
- V5: `docs/TEST_PLAN.md` asks for a consented real recording. Every live run used a recording made from two TTS voices, with synthetic contacts (`proof/LIVE-ACCEPT/proof.md`). The HubSpot note timing is real; the audio is not a real call. The owner should decide whether this meets GOAL item 5.
- V6: `V6.md` counts deliveries to a webhook sink, not HubSpot notes. The HubSpot note count (1 before, 1 after, same id) is in `proof/LIVE-ACCEPT/dup_crash.log`, independently verified in `proof/LIVE-ACCEPT/verified.md`.
- V8: the failing run came from pull request #3 and the passing run was started by hand (`workflow_dispatch`), because the PR's net diff was empty and its paths filter skipped the workflow. The Actions API shows no `pull_request` regression run on b8b121e. `docs/TEST_PLAN.md` does not restrict the event. The earlier verifier called this acceptable but not a literal PR check, and owner confirmation is still open. The Actions logs show one evaluated call per run (pass rate 0% with the bug, 100% without). This pass re-read those runs and did not trigger new ones.

**V9 misses its target.** Re-run against the EVAL-06 database dump restored into a fresh Postgres with the API on top: kappa 0.1892 on n = 30, recomputed 0.1892, target 0.6. The 95% bootstrap CI is -0.14 to 0.52 and raw agreement is 0.667 (`proof/EVAL-06/calibration.md`). This is `rubric-2026-10-v1`, the rubric in this release. The full EVAL-06 proof is on the unmerged branch `task/EVAL-06`; its verifier rejected the branch for mypy errors only and recomputed the same kappa (`proof/EVAL-06/rejected.md` on `qa/EVAL-07`). Later rubric work on unmerged branches is not counted here and has not reached 0.6: v2 held-out 0.00, v3 pooled on already-seen calls 0.43, v3 confirmation 0.595 on n = 15 after an owner correction (0.167 before it).

**V1 fails on two tasks.** EVAL-06 has its full proof on the unmerged branch, and H-02 was replaced by DIALECT-02 and has no proof of its own.

**V11 fails because the demo video and launch post links are not recorded.** The check used to match the template's "(not published yet)" text and would have passed; it now requires a URL. Repo visibility, the tag and the release page all check out. Gitleaks reports clean over all fetched refs after adding the reviewed false positives from `qa/FIX-VERIFY` to `.gitleaksignore` (a quoted test secret and gitleaks' own rule description).

**Screenshots still to retake.** `proof/FE-05/screenshots/regression-*.png` show "not enabled in this build" and `proof/QA-RC2-ui/dialect-*.png` show the empty state. They record those builds, not the current one. There is no capture yet of the promoted-regression page or of the dialect page with the real report. That needs the web app and workers on a full stack, plus the dialect run with owner keys; this pass only started Postgres and the API.

Sign-off needs every row PASS and Preetham approving the live demo in writing.
