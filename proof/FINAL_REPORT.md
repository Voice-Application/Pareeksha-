# Pareeksha final report

Generated 2026-10-27T17:06:52Z by `make verify` on commit 9ceedb851be825a70cea21cc9f9a4a8f4e2cba8e.
PASS only when the evidence file shows the check ran and met its criterion. FAIL = ran and missed (or could not run).
PENDING = needs an input only the owner can provide (HubSpot token, labelled calls, demo video, public repo...); it is not a pass.

| # | GOAL item | Result | Evidence |
|---|---|---|---|
| 1 | Every section-7 task has proof and a signed verified.md | **FAIL** | [proof/verify/V1.md](verify/V1.md) |
| 2 | compose up + make demo gives an evaluated call in < 20 min | **PASS** | [proof/verify/V2.md](verify/V2.md) |
| 4 | >= 4 of 5 planted bugs caught with cited turn indices | **PASS** | [proof/verify/V4.md](verify/V4.md) |
| 5 | Webhook-imported real recording audited, HubSpot note within 3 min | **PENDING** | [proof/verify/V5.md](verify/V5.md) |
| 6 | Duplicate delivery and worker crash give one evaluation and one CRM note | **FAIL** | [proof/verify/V6.md](verify/V6.md) |
| 7 | Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs | **PENDING** | [proof/verify/V7.md](verify/V7.md) |
| 8 | GitHub Action fails a PR enabling a mock bug, passes after the fix | **PENDING** | [proof/verify/V8.md](verify/V8.md) |
| 9 | Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6 | **PENDING** | [proof/verify/V9.md](verify/V9.md) |
| 10 | 8 adopter guides followed from a clean clone | **PENDING** | [proof/verify/V10.md](verify/V10.md) |
| 11 | Repo public, tagged v1.0.0, demo video + launch post published | **FAIL** | [proof/verify/V11.md](verify/V11.md) |

## V1: Every section-7 task has proof and a signed verified.md: FAIL

STATUS: FAIL
REASON: 11 task(s) without signed proof, 1 build-fail grep hit(s)

## V2: compose up + make demo gives an evaluated call in < 20 min: PASS

STATUS: PASS
REASON: evaluated call in 393s (7 scored evaluations)

## V4: >= 4 of 5 planted bugs caught with cited turn indices: PASS

STATUS: PASS
REASON: control (bugs off) pass rate 2/2; caught 5/5

## V5: Webhook-imported real recording audited, HubSpot note within 3 min: PENDING

STATUS: PENDING
REASON: needs HUBSPOT_TOKEN VERIFY_RECORDING_URL VERIFY_CONTACT_PHONE (HubSpot token, a consented real recording URL and a test contact)

## V6: Duplicate delivery and worker crash give one evaluation and one CRM note: FAIL

STATUS: FAIL
REASON: evaluations=1 duplicate deliveries=0 duplicate notes=0

## V7: Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs: PENDING

STATUS: PENDING
REASON: no dialect report exists; needs the owner's consented clips (H-02)

## V8: GitHub Action fails a PR enabling a mock bug, passes after the fix: PENDING

STATUS: PENDING
REASON: no recorded Actions run URLs

## V9: Judge vs Preetham labels on 30 calls: Cohen's kappa >= 0.6: PENDING

STATUS: PENDING
REASON: fewer than 30 human-labelled calls (EVAL-06 needs Preetham's labels)

## V10: 8 adopter guides followed from a clean clone: PENDING

STATUS: PENDING
REASON: 1 guide(s) need an owner key

## V11: Repo public, tagged v1.0.0, demo video + launch post published: FAIL

STATUS: FAIL
REASON: tag v1.0.0 does not exist (+0 more)

Sign-off needs every row PASS and Preetham approving the live demo in writing.

## Verifier addendum (qa/RC, tree b26ff54 + verifier proof commit)
`make verify` was run with V3 skipped (as instructed: no 40-call re-spend), so the table above has no V3 row.
- V3 (evidence inspected, not re-run): proof/QA-03 run 8422cb13: run_items 38 evaluated + 1 error + 1 judge_error = 40; 39/40 = 97.5% free of infra errors (95.0% counting the judge_error); consumer lag 0 and outbox backlog 0 files present. Criterion >= 95%: PASS on evidence. (Note: that run's pass_rate was 0.0, see QA-03 rejected.md.)
- V6 FAIL as run by the script: the default invocation had no webhook-sink receiver (`V6_SINK_LOG` unset), so it saw 1 evaluation but 0 deliveries and cannot show "exactly one delivery". The Kafka duplicate/crash suite inside V6 passed (9 passed). The builder's proof/RC/V6.md (with a sink receiver) is PASS but was not reproduced by the verifier.
- V2 PASS 393 s on a fresh clone (base images pre-pulled from the mirror because Docker Hub returned 429; image builds counted).
- V4 PASS 5/5 caught, bugs-off control 2/2 (this run, real services). Note the earlier QA-03 evidence had 4/5 and a failing clean matrix.
- V1 FAIL is expected: ALL-01, DOC-03, EVAL-06, H-01, H-02, PJM-01 have no proof; FE-03, INT-04, QA-02, QA-03, QA-04 are rejected; `STUB(FE-03)` remains.
- V5, V7, V8, V9, V10 (guide 5), V11: PENDING / FAIL on owner inputs as listed in each evidence file.
