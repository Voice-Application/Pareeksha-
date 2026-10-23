# INFRA-01 verified
Date: 2026-10-23. SHA verified: 80b7b3c (base merge-base 49c6392). Verifier worktree, clean checkout.
Re-run: `docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d --build` (needed BUILDX_BAKE_ENTITLEMENTS_FS=0 in this sandbox), then proof/INFRA-01/capture.sh. Output: proof/INFRA-01/verifier/health.txt (up.out too).
Results: kafka/postgres/api/mock-agent healthy; kafka-init and migrate Exited (0); web 200 on :3000; GET :8000/health -> 200 {"db":"ok","kafka":"ok"}; mock-agent /health ok; 12 pareeksha.* topics with expected partitions/retention; kafka-init re-run exit=0 and creates nothing; host listener :9094 answers. Differs from recorded health.txt only in project name, timestamps, topic IDs.
Stub scan (non-test): only STUB(TL-01), STUB(VOICE-03), STUB(FE-01), STUB(API-01); no STUB(INFRA-01), TODO, FIXME, NotImplementedError, skips. Stack torn down (down -v).
Note: diff vs current base shows deletions of DOC-01/PM-01 files only because the base moved past merge-base; not caused by this branch.
