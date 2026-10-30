# DOC-03 proof: 60-second demo script (STATUS: script done-unverified; recording BLOCKED ON OWNER)

Deliverable: `docs/demo-script.md`. AGENTS.md DOC-03: "60-second demo script (PRD section 9 incl. HubSpot note + GitHub Action); Preetham records."

- Covers all 8 PRD section 9 beats in a timed table (0 to 60 s): run, failing call with evidence, promote to regression, re-run passes, dialect heatmap,
  upload a real recording (Audits), HubSpot note, GitHub Action red then green.
- Exact click path uses the labels that exist in the web app (checked with `grep` in `web/components`: "Promote to regression",
  "Upload recording", "Re-run", "Compare"), and exact commands (`pareeksha run ...`, `pareeksha apply -f examples/ci/pareeksha.yaml`,
  the seed and compose commands from README/Guide 1). Planted-bug name `no_amount_confirm` is from `mock_agent/README.md`.
- Honesty rules are written into the script (the PRD's 72% is a design target, dialect numbers need real clips, no pasted HubSpot note, no keys on screen).
- The two Actions runs shown in the last beat are the recorded ones (`proof/QA-05/action_runs.txt`).

**Not done: the recording.** Preetham records; `proof/PJM-01/release.md` keeps an empty demo-video link. Nothing claims the video exists.

Check: `test -s docs/demo-script.md && grep -c '^| ' docs/demo-script.md` prints the table rows (9 beats + header + separator = 11).
