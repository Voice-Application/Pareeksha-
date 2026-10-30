# ALL-01 proof: QA's P0/P1 fixes (STATUS: done-unverified)

Task (docs/AGENTS.md section 7): "Fix only QA's P0/P1 bugs." No new code in this task: the P0/P1 findings were fixed
by FIX-01 (QA-03's P1 bugs) and FIX-02 (the independent verifier's rejections of QA-02/03/04, INT-04 and the V6/V4
harness findings). This file maps each finding to the fixing commit and to the evidence that it holds.
Both commits are ancestors of main (`git merge-base --is-ancestor <sha> origin/main`, run below).

Severity labels: FIX-01's own proof header says "P1 bugs from QA-03"; the repo contains no P0 finding. FIX-02's
findings come from the verifier's rejection notes and carry no P-label in the repo, they are listed here as
blocking (they made a QA task unverifiable), so ALL-01 treats them as P1. Where a verifier signed the result it is named.

## FIX-01 (P1 from QA-03), verified: `proof/FIX-01/verified.md` (independent, 2026-10-27, tree b26ff54)
| # | Finding | Fixing commit | Evidence |
|---|---|---|---|
| 1 | `inbound_url` pointed at the web app (404) | d69c1f5 FIX-01a/b | `test_inbound_url_ignores_the_web_app_base_url`, `proof/FIX-01/pytest_integrations.txt` |
| 2 | integrations worker dead-lettered every event (`KeyError 'SECRET_KEY'`) | d69c1f5 FIX-01a/b | `tests/unit/test_integrations_worker_startup.py` |
| 3 | `judge_error`: scores without cited turns invalid after the single repair | ec1899d FIX-01c | `test_scores_without_cited_turns_are_fixed_by_the_second_repair` and 2 more; follow-up test alignment 1c408ff / 5da9f03 |
| 4 | planted bug 2 (no amount read-back) flagged in 1 of 2 calls | 0ee8827 FIX-01d + aaf76f1 (mock-agent tool-call race, `check_amounts`) | `proof/FIX-01/results/bug2-no_amount_confirm.json`: 2 of 2 flagged; verifier V4: 5/5 caught |
| 5 | stale `web/lib/api/schema.d.ts` (found by the QA-04 contract test) | aaf76f1 | QA-04 contract test passes (verified.md of QA-04) |

## FIX-02 (verifier findings), evidence `proof/FIX-02/proof.md`; no verified.md of its own: the verifier signed QA-02, QA-03, QA-04 and INT-04 on tree 9b1ffbc (`grep -l FIX-02 proof/*/verified.md`)
| # | Finding | Fixing commit | Evidence |
|---|---|---|---|
| 1 | INT-04 SDK CI: `python-multipart` missing | bb5110e | `proof/FIX-02/pytest_sdk_clean_install.txt` (50 passed); INT-04 verified.md |
| 2 | QA-04 backend CI: jsonschema, types-PyYAML missing | bb5110e | `ruff_check.txt`, `mypy.txt`; QA-04 verified.md |
| 3 | QA-02 kafka-suite red in CI (`Unknown connector 'webhook'`, package not installed) | bb5110e | `kafka_suite_root_cause_repro.txt`; QA-02 verified.md |
| 4 | V6 needed a real sink | a1ddfe8 / 9b1ffbc | `proof/FIX-02/V6.md` (STATUS PASS) |
| 5 | QA-03 clean pass rate (mock agent policy) | bb5110e, a1ddfe8 | `results/clean-scenarios-final.json` 7 of 7; QA-03 verified.md (3 clean at 100, planted 5/5) |
| 6 | UI Overview, Run detail, Dialect | a1ddfe8, 9b1ffbc | `proof/FIX-02/screenshots/`; `proof/UI-REVIEW` 17/17 pages pass |

Release-candidate cleanup that came from the same verification round: 02b03e4 (remove lint/type suppressions, delete unused `api/stubs.py`).

## Commands (expected output)
```
for c in d69c1f5 ec1899d 0ee8827 aaf76f1 bb5110e a1ddfe8 9b1ffbc 02b03e4; do git merge-base --is-ancestor $c origin/main && echo "$c ancestor of main"; done
git grep -nE 'STUB\(|TODO|FIXME|NotImplementedError' -- backend/pareeksha mock_agent sdk/python/src action web/app web/components web/lib   # expected: no output
```
Real output is in `proof/ALL-01/check_ancestry.txt`.

## Not claimed
- No independent verified.md exists for ALL-01 (R2: not written by the builder).
- Clean-call pass rate is not deterministic (V4 control 2/2, then 1/2); this is noted by the verifier in QA-03/verified.md, not a P0/P1.
