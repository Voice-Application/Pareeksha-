# Pareeksha final report

Generated 2026-10-30T15:59:29Z by `make verify` on commit d9a99748d36413af0a5eaa425607d59888a3d2e6.
PASS only when the evidence file shows the check ran and met its criterion. FAIL = ran and missed (or could not run).
PENDING = needs an input only the owner can provide (HubSpot token, labelled calls, demo video, public repo...); it is not a pass.

| # | GOAL item | Result | Evidence |
|---|---|---|---|
| 1 | Every section-7 task has proof and a signed verified.md | **FAIL** | [proof/verify/V1.md](verify/V1.md) |
| 2 | compose up + make demo gives an evaluated call in < 20 min | **PASS** | [proof/verify/V2.md](verify/V2.md) |
| 4 | >= 4 of 5 planted bugs caught with cited turn indices | **PASS** | [proof/verify/V4.md](verify/V4.md) |
| 5 | Webhook-imported real recording audited, HubSpot note within 3 min | **PASS** | [proof/verify/V5.md](verify/V5.md) |
| 6 | Duplicate delivery and worker crash give one evaluation and one CRM note | **FAIL** | [proof/verify/V6.md](verify/V6.md) |
| 7 | Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs | **PENDING** | [proof/verify/V7.md](verify/V7.md) |
| 8 | GitHub Action fails a PR enabling a mock bug, passes after the fix | **PENDING** | [proof/verify/V8.md](verify/V8.md) |
| 9 | Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6 | **PENDING** | [proof/verify/V9.md](verify/V9.md) |
| 10 | 8 adopter guides followed from a clean clone | **PASS** | [proof/verify/V10.md](verify/V10.md) |
| 11 | Repo public, tagged v1.0.0, demo video + launch post published | **FAIL** | [proof/verify/V11.md](verify/V11.md) |

## V1: Every section-7 task has proof and a signed verified.md: FAIL

STATUS: FAIL
REASON: 6 task(s) without signed proof, 0 build-fail grep hit(s)

## V2: compose up + make demo gives an evaluated call in < 20 min: PASS

STATUS: PASS
REASON: evaluated call in 294s (11 scored evaluations)

## V4: >= 4 of 5 planted bugs caught with cited turn indices: PASS

STATUS: PASS
REASON: control (bugs off) pass rate 2/2; caught 5/5

## V5: Webhook-imported real recording audited, HubSpot note within 3 min: PASS

STATUS: PASS
REASON: HubSpot note created 15.1s after the signed POST

## V6: Duplicate delivery and worker crash give one evaluation and one CRM note: FAIL

STATUS: FAIL
REASON: Kafka suite failed

## V7: Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs: PENDING

STATUS: PENDING
REASON: no dialect report exists; needs the owner's consented clips (H-02)

## V8: GitHub Action fails a PR enabling a mock bug, passes after the fix: PENDING

STATUS: PENDING
REASON: no recorded Actions run URLs

## V9: Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6: PENDING

STATUS: PENDING
REASON: fewer than 30 human-labelled calls (EVAL-06 needs Preetham's labels)

## V10: 8 adopter guides followed from a clean clone: PASS

STATUS: PASS
REASON: all 8 guide logs end with RESULT: PASS

## V11: Repo public, tagged v1.0.0, demo video + launch post published: FAIL

STATUS: FAIL
REASON: tag v1.0.0 does not exist (+0 more)

Sign-off needs every row PASS and Preetham approving the live demo in writing.
