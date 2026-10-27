# Pareeksha final report (qa/RC2)

Assembled 2026-10-27 by the independent verifier from `scripts/verify/run_all.sh` runs on a fresh clone of 9b1ffbc (task/FIX-02), steps run in several invocations (container restarts interrupted one); V3 skipped by instruction. Each V file's STATUS is from its last run. V2: PASS in 156 s on a warm image cache (an earlier cold-cache run took 1581 s, mostly image build behind rate-limited Docker Hub). V4 PASS twice (control 2/2, later 1/2).
PENDING = needs an owner input; it is not a pass.

| # | GOAL item | Result | Evidence |
|---|---|---|---|
| 1 | Every section-7 task has proof and a signed verified.md | **FAIL** | [proof/verify/V1.md](verify/V1.md) |
| 2 | compose up + make demo gives an evaluated call in < 20 min | **PASS** | [proof/verify/V2.md](verify/V2.md) |
| 3 | 40-call Kafka run, >= 95% free of infra errors (skipped by instruction; not re-run) | **SKIPPED** | [proof/verify/V3.md](verify/V3.md) |
| 4 | >= 4 of 5 planted bugs caught with cited turn indices | **PASS** | [proof/verify/V4.md](verify/V4.md) |
| 5 | Webhook-imported real recording audited, HubSpot note within 3 min | **PENDING** | [proof/verify/V5.md](verify/V5.md) |
| 6 | Duplicate delivery and worker crash give one evaluation and one CRM note | **PASS** | [proof/verify/V6.md](verify/V6.md) |
| 7 | Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs | **PENDING** | [proof/verify/V7.md](verify/V7.md) |
| 8 | GitHub Action fails a PR enabling a mock bug, passes after the fix | **PENDING** | [proof/verify/V8.md](verify/V8.md) |
| 9 | Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6 | **PENDING** | [proof/verify/V9.md](verify/V9.md) |
| 10 | 8 adopter guides followed from a clean clone | **PENDING** | [proof/verify/V10.md](verify/V10.md) |
| 11 | Repo public, tagged v1.0.0, demo video + launch post published | **FAIL** | [proof/verify/V11.md](verify/V11.md) |

V1 detail: 20 tasks lack a signed verified.md on this branch (their sign-offs live on other qa/* branches) and 1 build-fail hit remains: `STUB(FE-03)` in web/app/runs/compare/page.tsx (FE-03 pending owner decision).

Sign-off needs every row PASS and Preetham approving the live demo in writing.
