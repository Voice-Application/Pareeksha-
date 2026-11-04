## Notes (records reconciled 2026-11-04)

**Not re-run.** No Gnani, DeepSeek or HubSpot keys were available for this pass, so these rows are the last harness results, not fresh ones:
- V2, V4, V5, V6: need the full stack and owner keys.
- V3: there is no evidence file because the step never finished through the harness. `proof/QA-03/proof.md` records 39/40 calls free of infrastructure errors (97.5%) in run 8422cb13, outside the harness. That does not count as a PASS here.
- V7: the 330 live speech calls were not repeated. The harness applied its criteria to the committed report that `proof/DIALECT-02/verified.md` verified, using the consent column in the manifest and the database count recorded by that run.
- V10: the step only re-read the existing guide logs. The 8 guides were not followed again.

**V9 misses its target.** Re-run against the EVAL-06 database dump restored into a fresh Postgres with the API on top: kappa 0.1892 on n = 30, recomputed 0.1892, target 0.6. The 95% bootstrap CI is -0.14 to 0.52 and raw agreement is 0.667 (`proof/EVAL-06/calibration.md`). This is `rubric-2026-10-v1`, the rubric in this release. The full EVAL-06 proof is on the unmerged branch `task/EVAL-06`; its verifier rejected the branch for mypy errors only and recomputed the same kappa (`proof/EVAL-06/rejected.md` on `qa/EVAL-07`). Later rubric work on unmerged branches is not counted here and has not reached 0.6: v2 held-out 0.00, v3 pooled on already-seen calls 0.43, v3 confirmation 0.595 on n = 15 after an owner correction (0.167 before it).

**V8 passes its written criterion, with one caveat.** The failing run came from pull request #3 and the passing run was started by hand (`workflow_dispatch`), because the PR's net diff was empty and its paths filter skipped the workflow. The Actions API shows no `pull_request` regression run on b8b121e. `docs/TEST_PLAN.md` does not restrict the event. The earlier verifier called this acceptable but not a literal PR check, and owner confirmation is still open. Each run's suite was one call (pass rate 0% with the bug, 100% without).

**V1 fails on two tasks.** EVAL-06 has its full proof on the unmerged branch, and H-02 was replaced by DIALECT-02 and has no proof of its own.

**V11 fails because the demo video and launch post links are not recorded.** The check used to match the template's "(not published yet)" text and would have passed; it now requires a URL. Repo visibility, the tag and the release page all check out. Gitleaks reports clean over all fetched refs after adding the reviewed false positives from `qa/FIX-VERIFY` to `.gitleaksignore` (a quoted test secret and gitleaks' own rule description).

**Screenshots still to retake.** `proof/FE-05/screenshots/regression-*.png` show "not enabled in this build" and `proof/QA-RC2-ui/dialect-*.png` show the empty state. They record those builds, not the current one. There is no capture yet of the promoted-regression page or of the dialect page with the real report. That needs the web app and workers on a full stack, plus the dialect run with owner keys; this pass only started Postgres and the API.
