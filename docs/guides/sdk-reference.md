# SDK and CLI reference (`pareeksha-sdk`)

Install: `pip install ./sdk/python` (from a clone) or `pip install pareeksha-sdk` once published. Python 3.11+. The import name is **`pareeksha_sdk`**; the command is `pareeksha`.

## Credentials

`pareeksha login --url http://localhost:8000 --key pk_live_...` writes `~/.config/pareeksha/config.toml` (override the path with `PAREEKSHA_CONFIG`). The environment variables `PAREEKSHA_URL` and `PAREEKSHA_KEY` take priority over the profile (use them in CI).

## Python

```python
from pareeksha_sdk import Pareeksha

with Pareeksha("http://localhost:8000", "pk_live_...") as pk:
    agent = pk.agents.get_by_name("EMI Reminder Bot")
    scenarios = [s.id for s in pk.scenarios.list() if "happy_path" in s.tags]
    persona = pk.personas.get_by_name("Manju — auto driver")
    noise = pk.noise_profiles.get_by_name("clean_16k")
    created = pk.runs.create(agent.id, scenarios, [persona.id], [noise.id], name="prompt v3", max_concurrency=1)
    run = pk.runs.wait(created.id, timeout_s=1800)
    print(run.status, run.summary.pass_rate, run.summary.critical_failures)

    call = pk.audits.create("call.wav", agent.id, "kn-IN")      # upload a recording
    done = pk.audits.wait(call.call_id)
```

| Resource | Methods |
|---|---|
| `pk.agents` | `list`, `get`, `get_by_name`, `create(body)`, `update(id, body)` |
| `pk.scenarios`, `pk.personas`, `pk.noise_profiles` | `list(**filters)`, `get_by_name`, `create(body)`, `update(id, body)` |
| `pk.runs` | `create(agent_id, scenario_ids, persona_ids, noise_profile_ids, *, name, repeats, max_concurrency, seed, dry_run, confirm_over_budget)`, `create_regression`, `get`, `items`, `cancel`, `wait(id, timeout_s, poll_s, on_progress)` |
| `pk.audits` | `create(file, agent_id, language, *, stereo_channels_are_speakers)`, `wait(call_id)` |
| `pk.dlq` | `list(status)`, `replay(id)`, `discard(id)` |
| `pk.health()`, `pk.metrics_summary()` | API health (`db`, `kafka`) and the `/metrics/summary` numbers |

`AsyncPareeksha` is the same surface with `await` / `async with`. 5xx and connection errors are retried; failures raise `ApiError` (has `.status`, `.code`), `NotFoundError`, `WaitTimeoutError`, `ConfigError`, all subclasses of `PareekshaError`.

## CLI

| Command | Does |
|---|---|
| `pareeksha login --url U --key K` | checks the API, saves the profile |
| `pareeksha apply -f pareeksha.yaml` | upserts agent, scenarios, personas, noise profiles by name; prints created/updated/unchanged |
| `pareeksha run [--agent N] [--tags a,b] [--suite S] [--persona P]... [--noise NP]... [--wait] [--fail-under PCT] [--timeout S] [--summary-file F]` | creates a run; `--wait` blocks; exit 1 when below the threshold or on a critical failure |
| `pareeksha regress --agent N [--wait/--no-wait]` | runs the blocking regression tests; exit 1 on suite failure |
| `pareeksha audit FILE --agent N --language kn-IN` | uploads a recording, waits, prints the result |
| `pareeksha dlq list [--status open]` / `dlq replay ID` | inspect and replay dead letters |
| `pareeksha doctor` | API, database, Kafka reachability plus DLQ/outbox counts; exit 1 if down |

Exit codes: 0 ok, 1 failed the gate, 2 error (unreachable, bad key, bad config). `GITHUB_STEP_SUMMARY` and `--summary-file` receive a Markdown summary.

## `pareeksha.yaml`

See `sdk/python/pareeksha.example.yaml` and [Guide 6](06-github-action.md). Top-level keys: `version: 1`, `agent`, `scenarios`, `personas`, `noise_profiles`, `suites`. A suite selects scenarios by `tags`, lists persona and noise-profile names, and may set `fail_under`, `repeats` and `max_concurrency`. Objects are matched by name, so the file is safe to apply repeatedly.
