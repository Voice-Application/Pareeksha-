# Guide 6 · Run tests on every pull request with the GitHub Action

Goal: a PR that changes your bot's prompt or `pareeksha.yaml` triggers a crash-test run against your Pareeksha instance; the check fails below your threshold or on a regression.

**Prerequisite:** a Pareeksha API reachable from GitHub's runners (a deployed instance; `localhost` will not work), an API key with scopes `read` and `runs:write` (web app, API keys), and your bot reachable from that instance.

## 1. Put your tests in the bot's repo

`pareeksha.yaml` (full example: `sdk/python/pareeksha.example.yaml`):

```yaml
version: 1
agent:
  name: EMI Reminder Bot
  adapter: audio_v1
  endpoint_url: wss://bot.example.com/ws
  languages: [kn-IN, hi-IN, en-IN]
  mandatory_disclosures:
    - {id: recording, regex: "(record|ರೆಕಾರ್ಡ್|रिकॉर्ड)", within_turns: 2}
scenarios:
  - title: Already paid, wants confirmation
    caller_goal: Say the EMI was paid yesterday and ask for confirmation.
    success_criteria: Agent verifies the payment instead of demanding it again.
    tags: [payment_dispute]
suites:
  pr_check:
    scenarios: {tags: [payment_dispute, happy_path]}
    personas: ["Manju — auto driver"]
    noise_profiles: [clean_16k, pstn_market_5db]
    fail_under: 80
```

`pareeksha apply -f pareeksha.yaml` upserts agent, scenarios, personas and noise profiles **by name**; it prints `created`/`updated`/`unchanged` per object and is safe to run on every PR. Personas and noise profiles referenced by a suite must exist (the seeded ones do).

## 2. Add the workflow

```yaml
# .github/workflows/voice-agent-tests.yml
on:
  pull_request:
    paths: ["prompts/**", "pareeksha.yaml"]
jobs:
  pareeksha:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: voice-application/pareeksha-/action@main
        with:
          api-url: ${{ secrets.PAREEKSHA_URL }}
          api-key: ${{ secrets.PAREEKSHA_KEY }}
          config: pareeksha.yaml
          suite: pr_check
          # fail-under: "80"        # overrides the suite's fail_under
          # regression: "true"      # also run the blocking regression suite
          # web-url: https://pareeksha.example.com   # deep links in the summary
          # sdk-package: "pareeksha-sdk @ git+https://github.com/voice-application/pareeksha-#subdirectory=sdk/python"
```

Add `PAREEKSHA_URL` (the API base URL, for example `https://pareeksha.example.com`) and `PAREEKSHA_KEY` as repository secrets. Pin the action to a tag or commit once you have one.

The composite action installs `pareeksha-sdk`, runs `pareeksha apply`, then `pareeksha run --suite pr_check --wait`, appends a Markdown summary (pass rate, failures, links) to `$GITHUB_STEP_SUMMARY`, and exits 1 on failure. Until the SDK is published to PyPI, set `sdk-package` to the git URL shown above.

## 3. What the exit codes mean

| Exit | Meaning |
|---|---|
| 0 | run completed and met `fail_under` (no critical failures) |
| 1 | pass rate below the threshold, a critical failure, or a regression |
| 2 | could not reach the API / bad key / bad config |

## 4. Run the same steps by hand

This is exactly what the action runs, so you can debug a failing check locally:

```bash
pip install ./sdk/python           # or: pip install pareeksha-sdk
export PAREEKSHA_URL=http://localhost:8000 PAREEKSHA_KEY=pk_live_...
pareeksha login --url "$PAREEKSHA_URL" --key "$PAREEKSHA_KEY"
pareeksha apply -f pareeksha.yaml
pareeksha run --suite pr_check -f pareeksha.yaml --wait --timeout 1800
pareeksha regress --agent "EMI Reminder Bot" --wait        # optional blocking regression suite
```

`pareeksha login` writes `~/.config/pareeksha/config.toml`; in CI the action passes `PAREEKSHA_URL` / `PAREEKSHA_KEY` as environment variables instead (they win over the profile).

## Tips

- Keep PR suites small (a few scenarios, one or two noise profiles): a call is real time, about a minute or two.
- Each run is priced; set `BUDGET_CREDITS` and `COST_*` in the instance's `.env` so an oversized suite is refused with `402 budget_exceeded`.
- `--fail-under` is a percentage of calls that passed the rubric; a call with a critical failure never passes.
