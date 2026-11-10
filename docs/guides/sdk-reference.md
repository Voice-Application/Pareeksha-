# SDK and CLI reference (`pareeksha-sdk`)

Install: `pip install ./sdk/python` (from a clone) or `pip install pareeksha-sdk` once published. Python 3.11+. The import name is **`pareeksha_sdk`**; the command is `pareeksha`.

## Credentials

`pareeksha login --url http://localhost:8000 --key pk_live_...` checks the API health, then writes `~/.config/pareeksha/config.toml` (override the path with `PAREEKSHA_CONFIG`; `XDG_CONFIG_HOME` is honoured). The environment variables `PAREEKSHA_URL` and `PAREEKSHA_KEY` (both must be set) take priority over the profile (use them in CI).

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
| `pk.agents` | `list(include_archived)`, `get`, `get_by_name`, `create(body)`, `update(id, body)` |
| `pk.scenarios`, `pk.personas`, `pk.noise_profiles` | `list(**filters)`, `get_by_name`, `create(body)`, `update(id, body)` |
| `pk.runs` | `create(agent_id, scenario_ids, persona_ids, noise_profile_ids, *, name, repeats, max_concurrency, seed, dry_run, confirm_over_budget)`, `create_regression(agent_id, *, statuses, name)`, `get`, `items`, `cancel`, `wait(id, timeout_s, poll_s, on_progress)` |
| `pk.audits` | `create(file, agent_id, language, *, stereo_channels_are_speakers)`, `wait(call_id, timeout_s, poll_s)` (returns when the call is `completed` or `error`) |
| `pk.dlq` | `list(status)`, `replay(id)`, `discard(id)` |
| `pk.kb` (sync only) | `create`, `list_all`, `get_by_name`, `update`, `upload`, `documents`, `delete_document`, `create_index`, `indexes`, `get_index`, `wait_index`, `generate_questions`, `import_questions` |
| `pk.rag` (sync only) | `create_matrix`, `get_matrix`, `wait_matrix`, `report(matrix_id, monthly_conversations)`, `pricing`, `set_prices` |
| `pk.health()`, `pk.metrics_summary()` | API health (`db`, `kafka`) and the `/metrics/summary` numbers |
| `pk.report_tool_calls(call_id, tool_calls)` | report a bot's tool calls after a call ([Guide 3](03-connect-any-bot.md)) |
| `pk.designer_chat(messages, draft)`, `pk.designer_commit(draft)` | test designer chat (stateless: send the whole history and last draft) and commit a ready draft |
| `pk.get_llm_settings()`, `pk.update_llm_settings(provider, *, base_url, judge_model, caller_model, designer_model, api_key)`, `pk.test_llm_settings()` | project-level LLM settings (admin key; the key is write-only) |
| `pk.create_prompt_version(agent_id, **fields)`, `pk.list_prompt_versions(agent_id)`, `pk.activate_prompt_version(agent_id, version)` | prompt-agent versions |

`AsyncPareeksha` has the same surface with `await` / `async with` (close with `aclose()`), except `kb` and `rag`, which exist only on `Pareeksha`. Clients take `timeout_s` (default 30), `max_retries` (3) and `backoff_s` (0.5); 5xx and connection errors are retried. Failures raise `ApiError` (has `.status_code`, `.code`, `.message`, `.details`), `NotFoundError`, `WaitTimeoutError`, `ConfigError`, all subclasses of `PareekshaError`.

## CLI

| Command | Does |
|---|---|
| `pareeksha login --url U --key K` | checks the API, saves the profile |
| `pareeksha apply -f pareeksha.yaml` | upserts agent, scenarios, personas, noise profiles by name; prints created/updated/unchanged |
| `pareeksha run [--agent N] [--tags a,b] [--suite S] [--persona P]... [--noise NP]... [-f FILE] [--wait/--no-wait] [--fail-under PCT] [--timeout S] [--poll S] [--summary-file F]` | creates a run; `--wait` blocks (implied by `--fail-under`); exit 1 when the pass rate is below the threshold, the run is cancelled, or it errored. `--suite` reads the agent, selectors and `fail_under` from the config |
| `pareeksha regress --agent N [--wait/--no-wait] [--timeout S] [--poll S] [--summary-file F]` | runs the blocking regression tests (waits by default); exit 1 on suite failure |
| `pareeksha audit FILE --agent N --language kn-IN [--timeout S] [--poll S]` | uploads a recording, waits, prints the result JSON; exit 1 if the call ends in `error` |
| `pareeksha dlq list [--status open]` / `dlq replay ID` | inspect and replay dead letters |
| `pareeksha prompt push --agent N --file F --provider P --model M [--tools F] [--temperature T] [--base-url U] [--note T]` | create a prompt version and make it active; `prompt versions --agent N`, `prompt activate --agent N VERSION`, `prompt set-key --agent N` (key from `PAREEKSHA_AGENT_API_KEY` or a hidden prompt) |
| `pareeksha kb create NAME [--local-only] [--description D] [--embedding-key-env VAR] [--reranker-key-env VAR]` | create a knowledge base; also `kb set-keys --kb N`, `kb upload --kb N FILE...` |
| `pareeksha kb index --kb N [--strategy fixed\|recursive\|sentence_window] [--size 800] [--overlap 100] [--embedding provider:model] [--wait]` | build an index (default embedding `local:intfloat/multilingual-e5-large`) |
| `pareeksha kb questions generate --kb N --agent A [--count 10] [--unanswerable-share 0.2]` / `questions import FILE --kb N --agent A` | draft or import ground-truth questions |
| `pareeksha rag run --agent A --kb N -f configs.json [--tags rag] [--persona P]... [--noise NP]... [--baselines/--no-baselines] [--repeats N] [--confirm-over-budget] [--wait]` | create a RAG matrix (one run per config plus baselines) |
| `pareeksha rag report MATRIX_ID [--monthly 10000] [--json]`, `rag pricing`, `rag set-price --kind llm\|embedding\|rerank --provider P --model M --input-per-m X [--output-per-m Y]` | comparison table and INR price table |
| `pareeksha doctor` | API, database, Kafka reachability plus DLQ/outbox counts; exit 1 if db or Kafka is down |

Exit codes: 0 ok, 1 failed the gate (or `kb index` failed), 2 error (unreachable, bad key, bad config, API error). `GITHUB_STEP_SUMMARY` and `--summary-file` receive a Markdown summary; set `PAREEKSHA_WEB_URL` to add an "Open run" link to it.

## `pareeksha.yaml`

See `sdk/python/pareeksha.example.yaml` and [Guide 6](06-github-action.md). Top-level keys: `version: 1` (the only supported value), `agent` (needs `name`), `scenarios` (each needs a unique `title`), `personas` and `noise_profiles` (each needs a unique `name`), `suites`. Unknown top-level keys, suite keys, and unknown agent or scenario fields are rejected. A suite selects scenarios by `tags` and/or `titles`, lists persona and noise-profile names, and may set `fail_under` (0 to 100), `repeats` (1 to 20) and `max_concurrency` (1 to 20). Any string value `file://relative/path` is replaced by that file's text (relative to the config). Objects are matched by name, so the file is safe to apply repeatedly.
