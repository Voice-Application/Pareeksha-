# Guide 9 · Test a prompt before you ship it

Goal: test a system prompt, a model and its tools as typed conversations, with no voice bot and no audio. You define a **prompt agent**, push a version, run scenarios against it, read the tool-call checks, and compare two versions.

**Prerequisite:** the stack from [Guide 1](01-quickstart.md), the CLI (`pip install -e sdk/python`) with `PAREEKSHA_API_KEY` set, and an API key for the model provider you want to test. `SECRET_KEY` must be set on the API (it encrypts the provider key).

## 1. Create a prompt agent

Web app: Agents, New agent, adapter **Prompt (text)**. There is no endpoint URL. Or by API:

```bash
API=http://localhost:${API_HOST_PORT:-8000}/api/v1
curl -s -X POST "$API/agents" -H "Authorization: Bearer $PAREEKSHA_API_KEY" -H "Content-Type: application/json" -d '{
  "name": "refund-bot",
  "description": "Answers refund questions for Acme Stores. Never waives fees without a manager.",
  "adapter": "prompt"
}'
```

## 2. Set the provider key

```bash
PAREEKSHA_AGENT_API_KEY=sk-... pareeksha prompt set-key --agent refund-bot
```

Without the env var the CLI asks for the key with a hidden prompt. The key is write-only: it is stored encrypted, and no API response, run snapshot, log or event contains it. The agent shows `has_adapter_secrets: true` once it is saved. Ollama and other keyless servers need no key.

## 3. Push a version

```bash
pareeksha prompt push --agent refund-bot --file prompt.md \
  --provider openai --model gpt-4o-mini --tools tools.json --note "first draft"
```

`prompt.md` is your system prompt as plain text. Every push creates an immutable version and makes it active. Pushing the same content again changes nothing. `pareeksha prompt versions --agent refund-bot` lists them, `pareeksha prompt activate --agent refund-bot 1` switches back. A run pins the version that was active when it was created, so later pushes never change a run in progress or a finished one.

Providers: `openai`, `openai_compatible`, `deepseek`, `groq`, `mistral`, `ollama` (all OpenAI chat-completions format), `anthropic`, `gemini`. For `openai_compatible` and `ollama` pass `--base-url`.

## 4. Write tools with mocks

`tools.json` is a list. Each tool has a name, a description, a JSON Schema for its parameters, and a `mock` that says what the tool returns. Pareeksha never calls your real backend in this mode.

```json
[
  {
    "name": "lookup_emi",
    "description": "Look up the customer's EMI",
    "parameters": {
      "type": "object",
      "properties": {"customer_id": {"type": "string"}},
      "required": ["customer_id"]
    },
    "mock": {"mode": "static", "result": {"emi": 4200, "due": "2026-11-10"}}
  },
  {
    "name": "refund_status",
    "description": "Status of a refund by order id",
    "parameters": {
      "type": "object",
      "properties": {"order_id": {"type": "string"}},
      "required": ["order_id"]
    },
    "mock": {
      "mode": "by_args",
      "cases": [
        {"when": {"order_id": "A100"}, "result": {"status": "paid"}},
        {"when": {"order_id": "A200"}, "result": {"status": "rejected"}}
      ],
      "result": {"status": "not_found"}
    }
  },
  {
    "name": "waive_fee",
    "description": "Waive a late fee",
    "parameters": {"type": "object", "properties": {"amount": {"type": "number"}}},
    "mock": {"mode": "simulated"}
  }
]
```

- `static`: always returns `result`.
- `by_args`: returns the `result` of the first case whose `when` keys all match the call's arguments, else the default `result`.
- `simulated`: a model invents a plausible result from the tool's description and the arguments. Use it when you do not want to write every case. If the simulation fails, the agent gets `{"error": "mock_unavailable"}`.

If the model sends arguments that are not valid JSON, the call is recorded with the raw text and the agent gets `{"error": "invalid_arguments"}`. A scenario can override one tool's mock by adding `mock_result` to its entry in `expected_tool_calls`.

## 5. Generate scenarios

Scenario generation reads the active system prompt, so the scenarios target what the prompt promises and forbids:

```bash
curl -s -X POST "$API/agents/<agent-id>/scenarios:generate" -H "Authorization: Bearer $PAREEKSHA_API_KEY" \
  -H "Content-Type: application/json" -d '{"count": 10, "mix": {"happy_path": 3, "edge_case": 4, "adversarial": 3}}'
```

Review the drafts in the web app and save the ones you want. To check tool use, set `expected_tool_calls` on the scenario:

```json
"expected_tool_calls": [
  {"name": "lookup_emi"},
  {"name": "waive_fee", "expect": "not_called"}
]
```

## 6. Run text tests

```bash
pareeksha run --agent refund-bot --tags smoke --wait
```

Each call is a typed conversation between a simulated caller (persona) and your model. Personas and noise profiles are selected as in a voice run, but noise is ignored. The run, judge and scoring work as in [Guide 1](01-quickstart.md). A call ends when the caller finishes, at the scenario's `max_turns`, or when the model keeps asking for tools past `max_tool_rounds` (event `tool_round_limit`). A provider error (bad key, rate limit, timeout) ends the call as `connect_failed` or `infra_error`; the message never contains your key.

**Cost estimate.** The pre-run estimate (`POST /runs:estimate`, the run wizard, and each RAG matrix entry) includes your model's tokens. It assumes one reply per caller line up to `max_turns`, and about 1.5 model rounds per reply when the version has tools. Each round resends the system prompt, the tool schemas, the history and the RAG context (`top_k` × chunk size for retrieval, the whole knowledge base for full context), so the figure errs high. The tokens are priced from **Settings → Pricing** (`llm`, your provider and model, ₹ per 1M tokens). Without a price they are counted in `agent_llm_tokens` but not in `est_cost`, and the estimate shows `agent_llm_unpriced: true`.

## 7. Read the tool-call checks

Open a call: the tool calls appear inline with their arguments and the mocked result. Three checks use them:

| Check | Passes when |
|---|---|
| `tool_calls_expected` | every expected tool was called with matching arguments (arguments match as a subset) |
| `tool_calls_expected` with `"expect": "not_called"` (key `not_called:<name>`) | the tool was never called |
| `no_unexpected_tool` | every call is a tool the scenario expects (one failure per extra call) |

A failed `tool_calls_expected` check adds the failure type `tool_selection` to the call. Evidence turns point at the turn that called the tool. Checks are stored per call, so a version change that starts calling a forbidden tool shows up in the call's checks even when the judge's overall score barely moves.

## 8. Compare two versions

Push the new prompt, run the same scenarios, then compare the two runs in the web app (Runs, select two, Compare) or `GET /runs/compare?base=<run>&head=<run>`. The response carries `base_prompt_version` and `head_prompt_version`, so the page reads "v1 to v2", and each cell has the call ids on both sides to open the conversations side by side. Cells that passed before and fail now are `newly_failing`. In the web app you can also diff two versions' prompts line by line from the agent page.

## Limits (phase 1)

- Text only. Call (voice) mode for prompt agents is not available yet; the voice adapters are unchanged.
- Tools are mocked. Pareeksha does not call your real tool backends.
- Tool arguments match by exact value (subset, numbers by value). Semantic matching comes later.
- No retrieval (RAG) testing yet; it comes later.
- Azure OpenAI and Bedrock are not supported yet. Token usage of the model under test is recorded as call events, not in cost reports.
- A `base_url` that points at a private, loopback or link-local address is rejected, so a tenant cannot make the API probe your network. For Ollama or any local endpoint, set `AGENT_LLM_ALLOW_PRIVATE_URLS=true` on the API and the simulator worker. Leave it off on shared deployments.
