# Goal (set by Preetham, 2026-10-23) — definition of done
Complete ALL tasks in AGENTS.md §7 and ship Pareeksha v1.0.0 as a public repo by Wed 28 Oct 2026, proven end to end against real services (Gnani, DeepSeek [default LLM; Gemini optional per owner 2026-10-23], Kafka, Postgres, HubSpot) by evidence an independent verifier re-ran.
Proof by kind: Code=pytest/Playwright 0 failed 0 skipped + coverage; Pipeline=run_id, call_ids, eval JSON, DB query output; Kafka=consumer offsets/lag + DLQ & retry test logs; Voice=caller/agent/mixed WAVs + real call transcript; UI=Playwright screenshots of every page with real data; Integrations=real HubSpot note ID + screenshot + webhook delivery log rows; CI/CLI=GitHub Actions run link, one failing and one passing PR check.
Verifier: clean checkout of commit, re-run every proof.md command, sign verified.md with date, SHA, own output; mismatch -> back to doing.
Build FAILS if outside tests/ and examples/: STUB(, TODO, FIXME, NotImplementedError, "pass  # placeholder", hardcoded fake results; mocked Gnani/DeepSeek/Gemini/HubSpot/Kafka in acceptance run; skipped/xfail tests or disabled lint/type checks; secrets, real personal data, unconsented voices (secret scan clean).
make verify (fresh clone) writes proof/FINAL_REPORT.md, all must PASS:
1 every §7 task has proof/ + signed verified.md
2 docker compose up + make demo -> evaluated call < 20 min (timed log)
3 40-call Kafka run, >=95% calls free of infra errors (run_id + query)
4 >=4/5 planted mock-agent bugs caught with cited turn indices
5 webhook-imported real recording audited, HubSpot note within 3 min (timestamps+note ID+screenshot)
6 duplicate delivery + worker-crash tests -> exactly one evaluation and one CRM note
7 dialect report: >=3 Kannada groups + Hindi + code-mixed, n + CIs (HTML)
8 GitHub Action fails PR enabling a mock bug, passes after fix (two run links)
9 judge vs Preetham labels on 30 calls: Cohen's kappa
10 each of 8 adopter guides followed from clean clone by verifier (log per guide)
11 repo public, tagged v1.0.0, demo video + launch post published (links)
STATUS.md "done" only with signed verified.md; unfinishable = NOT DONE with reason+evidence; §10 cuts need Preetham's written approval in CHANGELOG.md.
Sign-off: FINAL_REPORT all PASS AND Preetham watches demo live and approves in writing.
