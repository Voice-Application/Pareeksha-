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
- Speech: `STT_PROVIDER` / `TTS_PROVIDER` = `gnani` (default) | `google` | `azure` | `elevenlabs` | `deepgram`. Only Gnani is verified live today; the other four are implemented and unit-tested but their keys are pending, so treat them as untested against the real services. Each provider's variables are in `.env.example`.

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

This creates the 20 personas, the 8 noise profiles, the active rubric, the **EMI Reminder Bot** agent (pointing at the bundled mock agent, `ws://mock-agent:8765/ws`) with 8 scenarios, and an admin API key. It is get-or-create, so running it twice changes nothing. Because you pinned `PAREEKSHA_API_KEY` in `.env`, that exact value is the key (it is stored hashed). Restart the web app so it picks the key up:

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

## Troubleshooting

| Symptom | Fix |
|---|---|
| `kafka` unhealthy | Give Docker at least 4 GB RAM; `docker compose logs kafka` |
| `pareeksha doctor` 401 | the key in `.env` is not the one that was seeded; run the seed again after fixing `PAREEKSHA_API_KEY` |
| Calls end in `error` with 429 | Gnani allows one active request per key; set `SIMULATOR_REPLICAS=1` and run one call at a time |
| `docker pull` 429 from Docker Hub | log in (`docker login`) or pull through a mirror |

Stop everything: `docker compose --profile workers down` (add `-v` to delete the data volumes).

Next: [connect your own bot](02-connect-pipecat.md), [send recordings in](04-webhook-source.md), [gate PRs](06-github-action.md).
