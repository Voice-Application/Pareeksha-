# PJM-01 proof: release checklist (STATUS: partly done; owner items open)

Files: `checklist.md` (the checklist, what was run, what is open), `pii_grep.txt`, `secret_scan_fallback.txt`, `release.md` (format read by
`scripts/verify/v11_release.sh`, links honestly empty).

Run now: real-PII grep (clean, every hit classified in the checklist), noise-clip licences (none: noise is synthesised, `data/noise` absent),
third-party dialect audio licence (`data/dialect` absent), full-history secret scan **fallback** (0 hits). **Not run: gitleaks**: the pinned
8.30.0 binary was downloaded and its checksum verified, but this session's permission layer refused to execute it and the docker image pull
hit Docker Hub 429. `scripts/verify/v11_release.sh` now installs and runs it, so `make verify-step N=11` does the scan on a machine that allows it.

Left unchecked on purpose (owner): tag v1.0.0, demo video, launch post.

Commands: see `checklist.md`; expected outputs are the files above. V11 today (REST API visibility PUBLIC, tag absent): FAIL "tag v1.0.0 does not exist on origin" — correct until the owner creates the release.
