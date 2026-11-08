# Guide 1 · Quick start: clone to first evaluated call

Goal: run the whole platform on one machine and see one synthetic Kannada caller test the bundled mock EMI bot, judged end to end. Time: about 20 minutes, most of it the first image build.

**You need:** Docker with Compose v2, Python 3.11+, `git`, `openssl`, and two API keys: `GNANI_API_KEY` (speech) and `DEEPSEEK_API_KEY` (the default LLM for the caller brain and the judge). Gemini is a supported alternative (see step 2).

## 1. Clone and configure

```bash
git clone https://github.com/voice-application/pareeksha- pareeksha && cd pareeksha
cp .env.example .env
```

Edit `.env` and set:

| Variable | Value |
|---|---|
| `GNANI_API_KEY` | your Gnani key (speech default for both STT and TTS) |
| `DEEPSEEK_API_KEY` | your DeepSeek key (`LLM_PROVIDER=deepseek` is the default) |
| `SECRET_KEY` | a Fernet key, generate one with the command below |
| `PAREEKSHA_API_KEY` | the admin API key the seed will create, generate one with the command below |
| `SIMULATOR_REPLICAS` | `1` while you use a single Gnani key (it allows one active request at a time) |

```bash
echo "SECRET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')"      # paste into .env
echo "PAREEKSHA_API_KEY=pk_live_$(openssl rand -hex 24)"         # paste into .env
```

Later lines in `.env` win, so you can also append both lines instead of editing.

**Choosing providers (all in `.env`):**
- LLM: `LLM_PROVIDER=deepseek` (default; needs `DEEPSEEK_API_KEY`) or `LLM_PROVIDER=gemini` (needs `GEMINI_API_KEY`, `GEMINI_JUDGE_MODEL`, `GEMINI_CALLER_MODEL`).
- Speech: `STT_PROVIDER` / `TTS_PROVIDER` = `gnani` (default) | `google` | `azure` | `elevenlabs` | `deepgram`. Gnani is the only one used in full evaluated runs. ElevenLabs and Deepgram passed a live smoke test only (`proof/VOICE-07/verified-live.md`); Google and Azure are implemented and unit-tested but have not been run against the real services. Each provider's variables are in `.env.example`.

**Port clashes:** if 3000, 5432, 8000, 8765 or 9094 are taken, set `WEB_HOST_PORT`, `POSTGRES_HOST_PORT`, `API_HOST_PORT`, `MOCK_AGENT_HOST_PORT` or `KAFKA_HOST_PORT` in `.env`. Use `COMPOSE_PROJECT_NAME=<name>` to keep a second copy apart.

## 2. Start the stack

```bash
docker compose --profile workers up -d --build
docker compose ps
```

`--profile workers` starts the consumers (planner, simulator, evaluator, auditor, ...). Without it you only get Kafka, Postgres, the API, the web app and the mock agent. First build takes 5 to 10 minutes. Wait until `api` and `mock-agent` show `healthy`, then:

```bash
curl -s http://localhost:8000/health        # {"db":"ok","kafka":"ok"}
```

Behind a TLS-intercepting proxy, use the overlay for every compose command: `BUILDX_BAKE_ENTITLEMENTS_FS=0 CA_BUNDLE=/path/ca-bundle.crt docker compose -f docker-compose.yml -f docker-compose.proxy.yml --profile workers up -d --build` (it trusts the CA for the build and inside the containers, otherwise calls to Gnani/DeepSeek fail with `SSLError`). A normal machine does not need it.

## 3. Seed the demo data

```bash
docker compose run --rm api python -m pareeksha.seed
```

This creates the 20 personas, the 8 noise profiles, the active rubric, the **EMI Reminder Bot** agent (pointing at the bundled mock agent, `ws://mock-agent:8765/ws`) with 8 scenarios, and an admin API key. It is get-or-create, so running it twice changes nothing. Because you pinned `PAREEKSHA_API_KEY` in `.env`, that exact value is the key (it is stored hashed).

It also adds demo data, so the prompt and RAG pages are not empty on a fresh install. Every result in it was computed in advance; nothing calls an LLM and no API keys are needed. Every demo name starts with "Demo ·", and you can delete any of it:

- **Demo · Sahay EMI helpdesk**: a prompt agent with tool calls. v2 shortened the prompt and broke three of four scenarios. Open its two runs in **Runs → Compare** to see the regression.
- **Demo · Sahay Finance FAQ (EN + HI)**: a knowledge base of four FAQ documents (three English, one Hindi). It comes with 14 ground-truth questions and a finished RAG matrix on **RAG lab**, which compares three retrieval methods against no RAG and against the full knowledge base, with ₹ cost.
- The knowledge base's index is built by the `indexer` worker. The first build downloads the local embedding model, about 2.2 GB, once.
<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:7b883fc89bac4fcaca91ad5823d6c84e5eadd622be40779019fedd1dcca3520a -->

- Before saving a key on a demo agent, check its active version's provider and use a key matching that provider. New demos use DeepSeek's `deepseek-flash`; existing agents may still use another provider. To use a DeepSeek key, create and activate a DeepSeek version first if needed. The model under test uses the agent's own key, not the platform's.
- New demos select an illustrative peak estimate for `deepseek-flash` (₹26 input, ₹106 output per 1M tokens). The selected rate applies to all calls, including peak-hour calls; reports do not choose rates by call time. Older seeds may still have the off-peak estimate (₹13 input, ₹53 output), which also applies to all calls, including peak-hour calls. Check **Settings → Pricing** and adjust the rate to estimate peak costs; changes reprice existing reports. Reseeding preserves saved prices. These are demo estimates, not live provider billing rates.

<!-- /coderabbit-ai-generated:v1 -->

Restart the web app so it picks the key up:


```bash
docker compose up -d web
```

Open <http://localhost:3000>. The agent, personas and scenarios are listed.

## 4. Run one call from the CLI

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install ./sdk/python
set -a; . ./.env; set +a
pareeksha login --url http://localhost:${API_HOST_PORT:-8000} --key "$PAREEKSHA_API_KEY"
pareeksha doctor
pareeksha run --agent "EMI Reminder Bot" --tags promise_to_pay \
    --persona "Manju — auto driver" --noise clean_16k --wait
```

Exactly one scenario carries the `promise_to_pay` tag, so this is one call. A call is real time: expect about 2 minutes (Gnani allows one request at a time, so do not start several at once on one key). The CLI prints progress and ends with a line like

```
run <uuid>: completed, pass rate 0.0%, critical 1
```

Your numbers will differ: the caller is an LLM and the judge scores what it heard. (In our own run the judge flagged the bot for confirming a different EMI amount than the scenario's, a real finding.) The exit code is 0 when the run completed (add `--fail-under 80` to gate on a threshold). Open <http://localhost:3000/runs> to see the run: transcript, waveform, judge scores with evidence, and latency metrics for each call.

## 5. Plant a bug and watch the judge catch it

```bash
echo "MOCK_BUGS=no_disclosure" >> .env
docker compose up -d mock-agent
pareeksha run --agent "EMI Reminder Bot" --tags promise_to_pay --persona "Manju — auto driver" --noise clean_16k --wait
```

The mock agent now skips the recording disclosure, so the run reports a failed call. Other bugs: `no_amount_confirm`, `english_to_kannada`, `ignore_interrupt`, `false_waiver` (comma-separate to combine). Remove the line and `docker compose up -d mock-agent` to restore.

The mock agent's voice detection goes by loudness, so on `auto_rickshaw_0db` it can stop answering and the call ends `agent_silent`. That is a limit of the mock, not a finding about a real bot: see [its README](../../mock_agent/README.md#noisy-lines).

## Design tests by chat

Instead of writing the agent, scenarios and personas by hand, paste your bot's prompt or workflow into the test designer. It asks only what it cannot infer (endpoint URL, languages, mandatory disclosures, tools, target callers, line conditions), then returns a draft you commit in one call:

```python
from pareeksha_sdk import Pareeksha

client = Pareeksha(base_url="http://localhost:8000", api_key="pk_live_...")
messages = [{"role": "user", "content": open("bot_prompt.txt").read()}]
reply = client.designer_chat(messages)          # reply["questions"]: what it still needs
messages += [{"role": "assistant", "content": reply["reply"]},
             {"role": "user", "content": "ws://my-bot:8765/ws, Hindi and Kannada, recorded-call disclosure"}]
reply = client.designer_chat(messages, draft=reply["draft"])
if reply["ready"]:
    done = client.designer_commit(reply["draft"])  # agent + scenarios + personas, one transaction
    print(done["calls"], "calls; review and start the run at", done["run_wizard_path"])
```

The chat is stateless: send the whole history each time. Open `run_wizard_path` in the web app to review and start the run.

### Choose the LLM per project

DeepSeek is the default (set `DEEPSEEK_API_KEY` in `.env`). An admin key can override it for one project, without a restart: `client.update_llm_settings(provider="gemini", judge_model="...", caller_model="...", api_key="...")`, or `provider="openai_compatible"` with an https `base_url` of any OpenAI-compatible API. `client.test_llm_settings()` makes one tiny call to check it; `DELETE /settings/llm` goes back to `.env`. The key is write-only: the API only shows its last four characters.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `kafka` unhealthy | Give Docker at least 4 GB RAM; `docker compose logs kafka` |
| `kafka-init` fails with `set: pipefail: invalid option name`, or `migrate` with `Can't locate revision identified by 'head'` | The scripts have CRLF line endings (a Windows clone from before `.gitattributes` forced LF). Pull, check them out again and rebuild: `git pull && rm infra/kafka/create-topics.sh backend/alembic_migrate.sh && git checkout -- infra/kafka/create-topics.sh backend/alembic_migrate.sh && docker compose --profile workers up -d --build` |
| `pareeksha doctor` 401 | the key in `.env` is not the one that was seeded; run the seed again after fixing `PAREEKSHA_API_KEY` |
| Calls end in `error` with 429 | Gnani allows one active request per key; set `SIMULATOR_REPLICAS=1` and run one call at a time |
| `docker pull` 429 from Docker Hub | log in (`docker login`) or pull through a mirror |

Stop everything: `docker compose --profile workers down` (add `-v` to delete the data volumes).

Next: [connect your own bot](02-connect-pipecat.md), [send recordings in](04-webhook-source.md), [gate PRs](06-github-action.md).
