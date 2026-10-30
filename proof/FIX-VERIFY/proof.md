# FIX-VERIFY proof (STATUS: done-unverified; branch task/FIX-VERIFY from main 6ebe99b)

Fixes to the verify harness that were not product failures. No check criterion was changed.

| V | Change | Result after the fix |
|---|---|---|
| V6 | `scripts/verify/v06_duplicates.sh` runs `pytest tests/kafka` from `.venv-verify` (python3.12; `requirements.txt` + `backend/requirements-dev.txt` + `pip install --no-deps -e backend`, exactly the kafka-suite.yml recipe); reused when present; install failure => FAIL "cannot build the backend dev environment" (never PASS) | **PASS** live, `V6_live_run.md`: Kafka suite 9 passed (`V6_kafka_suite.txt`, Python 3.12.3), sink ping HTTP 200, new call evaluated, 2 re-publishes + SIGKILL: evaluations 1/1, sink hits 1, duplicate delivery keys 0, duplicate note ids 0 |
| V8 | `step8_github_action.sh` reads runs through `gh`, else `curl https://api.github.com/repos/<slug>/actions/runs/<id>`; fetches the two SHAs when missing so the descendant test can run; `proof/QA-05/action_runs.txt` holds the two run URLs | **FAIL** (honest): API says failure then success of the same workflow `pareeksha-regression`, but the commits are not ancestor/descendant (`fresh_clone/V8.md`) |
| V11 | `v11_release.sh`: tag via `git ls-remote --tags origin v1.0.0`, visibility via REST `private`, gitleaks pinned 8.30.0 (download + sha256 check, else docker image) | **FAIL** while the tag is absent: visibility PUBLIC (REST `private:false`), repo URL 200, "tag v1.0.0 does not exist on origin". gitleaks NOT executed (see Issues) |
| V1 | proofs written: ALL-01, H-01, DOC-03, PJM-01 (+ docs/demo-script.md) | still **FAIL**, 6 -> the same 6 ids but reasons changed: ALL-01/DOC-03/H-01/PJM-01 now lack only the independent `verified.md` (R2); EVAL-06 and H-02 untouched by design (`fresh_clone/V1.md`) |

## Run record
- V8 API check done by me (unauthenticated REST, 2026-10-30): run 40894601670 `pareeksha-regression` completed `failure`, head_sha 8708a927c5dfe1c1216747e465cfb917dfe91cf1, branch ci-test/bug-on; run 40894620111 `pareeksha-regression` completed `success`, head_sha ea08f12ebdf9e6ffc76b4f88e6e4eb7a1bd85886, branch ci-test/bug-fixed. merge-base of the two = 7b51e34: siblings, so "second descends from first" is `no`. The earlier pair 40728736209 (failure @16dd2ee, an ancestor of ea08f12) -> 40894620111 would descend, but that failure predates FIX-CI and was not shown to be a judged failure, so I did not substitute it.
- Repo visibility: `curl https://api.github.com/repos/Voice-Application/Pareeksha-` => `private: false`. `git ls-remote --tags origin v1.0.0` => empty.
- V6 ran on the working tree of this commit (the stack is not re-creatable twice here: Docker Hub 429s). V1, V8 ran from a fresh clone of 96f23ac. Stack: `docker compose -f docker-compose.yml -f docker-compose.proxy.yml --profile workers up -d --build` with real Gnani + DeepSeek, then `python -m pareeksha.seed`.
- Bookkeeping proofs: `proof/ALL-01`, `proof/H-01` (fresh Gnani TTS+STT 200/200, DeepSeek 200 `deepseek-flash`), `proof/DOC-03`, `proof/PJM-01`.

## Issues / not done
1. gitleaks was not executed. The checksum-verified binary download worked; the permission layer refused to run it twice, and the docker image pull hit Docker Hub 429. Needs the owner to allow it or to run `make verify-step N=11` elsewhere.
2. V11's release.md check greps for the words video/launch, so honest empty links still satisfy those two sub-checks; V11 still FAILs on the missing tag, and the real link check is HTTP 200 on URLs that are present.
3. V8 needs a run pair on descending commits (e.g. push a fix commit onto the failing PR branch) or a decision from the owner on the criterion.
4. Did not commit proof/FINAL_REPORT.md (verifier regenerates it).
