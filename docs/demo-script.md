# Pareeksha 60-second demo script (DOC-03)

Source: PRD section 9 (demo storyline), `docs/AGENTS.md` row DOC-03. Target runtime 60 s of finished video;
the live steps below are pre-run, and the recording cuts between a pre-recorded result and the live click.

**Recording status: BLOCKED ON OWNER.** Preetham records the video and the voice-over. Nothing in this repo claims the
video exists; `proof/PJM-01/release.md` carries an empty demo-video link until it is published.

## 0. Setup (before pressing record, not on camera)

Needs the stack from [Guide 1](guides/01-quickstart.md), a HubSpot private-app token (owner, H-01), and the GitHub repo
with the two CI test PRs (GOAL item 8).

```bash
cp .env.example .env    # set GNANI_API_KEY, DEEPSEEK_API_KEY, SECRET_KEY, PAREEKSHA_API_KEY, SIMULATOR_REPLICAS=1
docker compose --profile workers up -d --build
docker compose run --rm api python -m pareeksha.seed         # personas, noise profiles, rubric, "EMI Reminder Bot", API key
pip install ./sdk/python && pareeksha login --url http://localhost:8000 --key "$PAREEKSHA_API_KEY"
```

Pre-run (so the 60 s needs no waiting; each takes 3 to 6 minutes because Gnani allows one request at a time):

1. A run with a planted bug on: `MOCK_BUGS=no_amount_confirm` mock-agent container (see `mock_agent/README.md`), run
   "EMI Reminder Bot" against "Promise to pay on Friday" x "Manju" x `pstn_8k_alaw`. Keep the run URL (`/runs/<id>`).
2. The same run against the clean mock agent (second run, passes) for the Regression and compare shots.
3. HubSpot: Integrations, Add integration, HubSpot, paste the token, `match_by: phone`; a test contact whose phone
   equals the uploaded recording's `metadata.phone`.
4. One recording to upload (consented, `data/` or the owner's call) at `~/demo/call.wav`.
5. The two GitHub PRs: `ci-test/bug-on` (red) and `ci-test/bug-fixed` (green), links in
   <https://github.com/Voice-Application/Pareeksha-/actions/runs/40894601670> and
   <https://github.com/Voice-Application/Pareeksha-/actions/runs/40894620111>.

## 1. Shot list (60 s)

| t (s) | Screen and exact action | Voice-over (about 2 words per second) |
|---|---|---|
| 0 to 6 | Terminal: `pareeksha run --agent "EMI Reminder Bot" --tags promise_to_pay --persona "Manju — auto driver" --noise pstn_8k_alaw --wait` (sped up, cut to the result line) | "Voice bots fail on Indian lines. Pareeksha crash-tests them before launch." |
| 6 to 14 | Browser `http://localhost:3000`, sidebar **Runs**, click the pre-run, show the pass rate tile and the score heatmap | "Forty synthetic callers: Kannada, Hindi, Kanglish, noisy 8 kHz." |
| 14 to 24 | In the heatmap click the red cell, which opens the call page. Click the highlighted evidence turn (the transcript scrolls and the waveform seeks), press play | "A critical failure: the caller said four thousand, the bot confirmed forty thousand. The judge cites the exact turn." |
| 24 to 30 | Call page, button **Promote to regression**, confirm in the dialog | "One click turns it into a permanent regression test." |
| 30 to 36 | Sidebar **Runs**, open the re-run, **Compare** with the failing run (Run compare page), the cell flips red to green | "Fix the prompt, re-run, it passes." |
| 36 to 43 | Sidebar **Dialect**, open the latest report, point at the lowest-entity-accuracy cell (low-n cells are hatched) | "The dialect report shows where accuracy drops, with sample sizes." |
| 43 to 50 | Sidebar **Audits**, **Upload recording**, choose `~/demo/call.wav`, submit, cut to the finished audit: score plus the missing-disclosure flag | "Upload a real recording: same rubric, flags the missing disclosure." |
| 50 to 55 | HubSpot tab: the test contact, Activity, the note "Pareeksha call audit" (HubSpot note appears within 3 minutes of the audit) | "The note lands on the HubSpot contact by itself." |
| 55 to 60 | GitHub tab: PR `ci-test/bug-on` Checks tab, `pareeksha-regression` red; PR `ci-test/bug-fixed`, green | "And a pull request fails the check until the bug is fixed." |

Alternative to the Audits click for the import step (shows the signed webhook source): Guide 4 section "send a call",
`curl -X POST` to the integration's `inbound_url` with `X-Pareeksha-Timestamp` and `X-Pareeksha-Signature` headers.

## 2. Exact commands used on camera

```bash
pareeksha run --agent "EMI Reminder Bot" --tags promise_to_pay --persona "Manju — auto driver" --noise pstn_8k_alaw --wait
pareeksha apply -f examples/ci/pareeksha.yaml        # only if the GitHub Action shot is replayed locally
```

Nothing else is typed; every other step is a click (names above are the labels in the web app).

## 3. Honesty rules for the recording

- The 72% pass rate in the PRD storyline is a design target, not a number to quote. Show the real pass rate of the
  real run and say it.
- Dialect numbers come from real consented clips (H-02). Until those exist, do not record the Dialect shot as a finding
  (synthetic groups are labelled as such in the report).
- Show the HubSpot note only if it was produced by the live integration (not pasted).
- No keys on screen: `.env` is never opened; the API key field in the UI is masked.

## 4. Owner checklist

- [ ] HubSpot token and test contact (H-01)
- [ ] Consented recording for the Audits shot
- [ ] Record, edit to 60 s, publish, put the link in `proof/PJM-01/release.md`
