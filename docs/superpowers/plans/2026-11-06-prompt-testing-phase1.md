# Prompt Testing (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A customer can define a "prompt agent" (system prompt + model + mocked tools), version it, generate test cases from it, run them as text conversations against a simulated user, see tool-call checks, and compare two versions.

**Architecture:** New agent adapter value `prompt`. Prompt definitions live in an immutable `prompt_versions` table; `agents.adapter_config.active_version_id` points at the active one, so the run's existing `agent_snapshot` pins the version used. The simulator worker branches in `_run_call` to a new text runner that produces the same `CallResult` the voice path produces, so storage, evaluator, judge, compare and sinks run unchanged. The model under test is called through a new `pareeksha/agent_llm/` package (httpx, native tool calling), separate from the frozen JSON-only `pareeksha/llm/` contract.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, Alembic, httpx, pydantic v2, pytest (asyncio auto); Next.js + openapi-fetch web; Python SDK/CLI (typer).

**Spec:** `docs/superpowers/specs/2026-11-06-prompt-and-rag-testing-design.md` (phase 1 of its build order).

## Global Constraints

- No new dependencies in phase 1 (httpx, pydantic, typer already installed).
- Do not modify `backend/pareeksha/llm/base.py` (frozen contract), `docs/schema.sql` or `backend/alembic/sql/0001_initial.sql` (byte-identical test).
- All new tables are tenant-scoped by `project_id` and every route uses the agents router's existing project dependency.
- Secrets (provider API keys) are write-only: never returned by any API, never in `agent_snapshot`, logs, events, errors or exception messages.
- `make lint` (ruff check, ruff format --check, mypy; web eslint + tsc) and `make test` stay green; existing voice-path tests unchanged.
- Backend unit tests must not need Postgres; DB-touching tests go under `backend/tests/integration` or `backend/tests/db`.

## Deliberate phase-1 deferrals (from the spec; marked `ponytail:` in code where relevant)

- `run_items.noise_profile_id` stays NOT NULL: text runs take persona + noise like voice runs and ignore noise. Nullable noise + RAG config dimension come with phase 3.
- `match: "semantic"` tool-argument matching: phase 2. Phase 1 matches args as today (subset, `_value_eq`).
- Providers in phase 1: `openai`, `openai_compatible`, `deepseek`, `groq`, `mistral`, `ollama` (all OpenAI chat-completions wire format), `anthropic`, `gemini`. Azure OpenAI and Bedrock: phase 2.
- Agent-LLM token usage is recorded as call events, not in `api_usage`/estimates (cost reporting is phase 4).
- Call (voice) mode for prompt agents: phase 2.

## Review Focus

1. Model keeps requesting tools forever → after `max_tool_rounds` the turn ends, event `tool_round_limit` recorded, call ends `agent_silent`; never an infinite loop. (Task 4 test.)
2. Model returns tool-call arguments that are not valid JSON → recorded with `{"_raw": "<text>"}` arguments and a mock result `{"error": "invalid_arguments"}` sent back; call continues. (Task 2 + Task 4 tests.)
3. Provider 401/429/5xx/timeout → call ends `connect_failed` (no agent turn yet) or `infra_error` with a message that contains no API key; worker does not crash. (Task 2 + Task 4 tests.)
4. API key leakage → `AgentOut`, `agent_snapshot`, list endpoints and error bodies never contain the key. (Task 5 test asserting the literal key string is absent from responses.)
5. `base_url` pointing at internal addresses (SSRF) → rejected unless `AGENT_LLM_ALLOW_PRIVATE_URLS=true`. (Task 5 test.)

---

### Task 1: Schema, migration, shared types

**Files:**
- Create: `backend/alembic/versions/0004_prompt_versions.py` (revises `0003_llm_settings`)
- Create: `backend/pareeksha/schemas/prompts.py`
- Modify: `backend/pareeksha/db/models.py` (Agents adapter CHECK ~454; checks `check_type` CHECK ~594; new `PromptVersions` class next to `Users`)
- Modify: `backend/pareeksha/adapters/base.py:27` (`AdapterName` add `"prompt"`), `backend/pareeksha/schemas/common.py:12` (`AdapterType` add `"prompt"`)
- Modify: `backend/tests/db/test_migrations.py` (tables added after the v0.2 schema: subtract `{"users", "llm_settings", "prompt_versions"}` from the live set before comparing; table count assertion becomes documented + those)
- Test: `backend/tests/unit/test_prompt_schemas.py`

**Interfaces — Produces:**
- `ProviderName = Literal["openai","openai_compatible","deepseek","groq","mistral","ollama","anthropic","gemini"]`
- `MockCase(when: dict[str, Any], result: dict[str, Any])`
- `MockSpec(mode: Literal["static","by_args","simulated"]="static", result: dict[str, Any] = {}, cases: list[MockCase] = [])`
- `PromptTool(name: str  # ^[A-Za-z0-9_-]{1,64}$, description: str = "", parameters: dict[str, Any]  # JSON Schema, must have "type": "object", mock: MockSpec = MockSpec())`
- `PromptVersionCreate(system_prompt: str  # 1..100_000 chars, provider: ProviderName, model: str  # 1..200, base_url: str | None = None, temperature: float = 0.2  # 0..2, tools: list[PromptTool] = []  # max 64, unique names, max_tool_rounds: int = 5  # 1..10, note: str = ""  # max 500)`
- `PromptVersionOut(PromptVersionCreate)` + `id: UUID, agent_id: UUID, version: int, content_hash: str, created_at: datetime`
- `def content_hash(body: PromptVersionCreate) -> str` — sha256 hex of `json.dumps(body.model_dump(mode="json", exclude={"note"}), sort_keys=True, separators=(",", ":"))`.
- Table `prompt_versions`: `id uuid pk default gen_random_uuid()`, `project_id uuid not null fk projects on delete cascade`, `agent_id uuid not null fk agents on delete cascade`, `version int not null`, `system_prompt text not null`, `provider text not null`, `model text not null`, `base_url text null`, `temperature real not null`, `tools jsonb not null default '[]'`, `max_tool_rounds int not null default 5`, `rag_config jsonb not null default '{}'`, `note text not null default ''`, `content_hash text not null`, `created_at timestamptz not null default now()`; `UNIQUE (agent_id, version)`; index `prompt_versions_agent_id_idx`.
- Constraint changes (in 0004, reversible): `agents_adapter_check` gains `'prompt'`; the checks table `check_type` constraint gains `'no_unexpected_tool'` (find its exact name in `docs/schema.sql` / models.py around line 594).

- [ ] **Step 1: Write failing tests** in `test_prompt_schemas.py`: `test_tool_names_must_be_unique` (two tools named `refund` → ValidationError), `test_tool_parameters_must_be_object_schema` (`{"type":"string"}` → ValidationError), `test_content_hash_ignores_note` (same body, different `note` → equal hash; different `temperature` → different hash), `test_prompt_is_valid_adapter` (`AgentTarget(..., adapter="prompt", ...)` validates).
- [ ] **Step 2: Run** `cd backend && python -m pytest tests/unit/test_prompt_schemas.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `schemas/prompts.py`, the literal changes, `PromptVersions` model, and migration `0004` (revision `"0004"`, down_revision `"0003"`, `op.create_table` style like 0002; constraint swaps via `op.drop_constraint`/`op.create_check_constraint`; downgrade restores the old constraints and drops the table).
- [ ] **Step 4: Run** the unit test → PASS; then `cd backend && ruff check . && mypy`. If Postgres is available, `python -m pytest tests/db -q` → PASS (including downgrade/upgrade round trip).
- [ ] **Step 5: Commit** `feat(prompt): prompt_versions table, prompt adapter type, version schemas`.

### Task 2: Agent-LLM provider package (model under test)

**Files:**
- Create: `backend/pareeksha/agent_llm/__init__.py`, `base.py`, `openai_compat.py`, `anthropic.py`, `gemini.py`, `factory.py`, `mocks.py`, `url_guard.py`
- Test: `backend/tests/unit/agent_llm/test_providers.py`, `test_mocks.py`, `test_url_guard.py`
- `url_guard.check_base_url(url: str, *, allow_private: bool) -> None` raises `ValueError` for non-http(s) schemes and, unless `allow_private`, for hosts resolving to loopback/private/link-local/metadata addresses (stdlib `ipaddress` + `socket.getaddrinfo`). Add setting `AGENT_LLM_ALLOW_PRIVATE_URLS` (default false) to the existing settings module. Reuse an existing endpoint-URL validator if the codebase has one. Tests: public https passes; `http://169.254.169.254/`, `http://127.0.0.1:8080`, `http://10.0.0.5`, `file:///etc/passwd` raise; loopback passes with `allow_private=True`.

**Interfaces — Consumes:** `ProviderName`, `PromptTool`, `MockSpec` (Task 1).
**Produces (`agent_llm/base.py`, frozen dataclasses):**
- `ToolSpec(name: str, description: str, parameters: dict[str, Any])`
- `ToolCallReq(id: str, name: str, arguments: dict[str, Any], raw_arguments: str)` — invalid JSON → `arguments={"_raw": raw_arguments}`.
- `AgentMessage(role: Literal["system","user","assistant","tool"], content: str, tool_calls: tuple[ToolCallReq, ...] = (), tool_call_id: str | None = None, name: str | None = None)`
- `ChatReply(text: str, tool_calls: tuple[ToolCallReq, ...], input_tokens: int, output_tokens: int, latency_ms: int)`
- `class AgentLLMError(Exception)` with `status: int | None`, `retryable: bool`; message never includes the API key or request headers.
- `class ChatProvider(Protocol): async def chat(self, messages: Sequence[AgentMessage], tools: Sequence[ToolSpec], *, model: str, temperature: float, timeout_s: float = 60.0) -> ChatReply`
- `factory.build_chat_provider(provider: ProviderName, *, api_key: str | None, base_url: str | None = None, http: httpx.AsyncClient | None = None) -> ChatProvider`. Default base URLs: openai `https://api.openai.com/v1`, deepseek `https://api.deepseek.com`, groq `https://api.groq.com/openai/v1`, mistral `https://api.mistral.ai/v1`, ollama `http://localhost:11434/v1`; `openai_compatible` requires `base_url` (ValueError otherwise). Anthropic: `https://api.anthropic.com/v1/messages`, header `anthropic-version: 2023-06-01`, system prompt as top-level `system`, tools as `{name, description, input_schema}`, tool results as `tool_result` blocks; a leading assistant turn is not allowed so the runner always starts with a user message. Gemini: `generateContent` REST with `systemInstruction`, `tools[].functionDeclarations`, `functionResponse` parts. Builder verifies each wire format against current provider docs.
- `mocks.mock_result(tool: PromptTool, arguments: dict[str, Any], override: dict[str, Any] | None, simulate: Callable[[PromptTool, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None) -> Awaitable[dict[str, Any]]` — order: `override` if given → `by_args`: first case whose `when` is a subset of arguments (reuse `evaluation/checks.py::_value_eq` semantics), else `tool.mock.result` → `static`: `tool.mock.result` → `simulated`: `await simulate(tool, arguments)`; any simulate failure → `{"error": "mock_unavailable"}`. Arguments containing `_raw` → `{"error": "invalid_arguments"}`.

- [ ] **Step 1: Failing tests** with `httpx.MockTransport` (no network): per provider family, `test_<family>_parses_text_reply`, `test_<family>_parses_tool_call` (name + parsed args + id), `test_<family>_sends_tools_and_system` (inspect request JSON), `test_invalid_tool_arguments_kept_raw` (openai family, `arguments: "{bad"` → `{"_raw": "{bad"}`), `test_http_errors_raise_agent_llm_error` (401 → `retryable=False`, 429/503 → `retryable=True`; `"sk-test-secret" not in str(exc)`), `test_openai_compatible_requires_base_url`. Mocks: `test_override_wins`, `test_by_args_first_matching_case`, `test_by_args_falls_back_to_result`, `test_simulated_failure_returns_error`, `test_raw_arguments_return_invalid_arguments`.
- [ ] **Step 2: Run** `python -m pytest tests/unit/agent_llm -q` → FAIL.
- [ ] **Step 3: Implement.** One OpenAI-format client class parameterised by base URL; `latency_ms` measured around the HTTP call; usage from provider response (0 when absent). No retries inside the provider (the runner decides).
- [ ] **Step 4: Run** tests → PASS; ruff + mypy clean.
- [ ] **Step 5: Commit** `feat(agent_llm): tool-calling chat providers and tool mocks`.

### Task 3: Prompt versions API, agent secrets, test-connection

**Files:**
- Create: `backend/pareeksha/api/routers/prompt_versions.py` (register in `api/main.py` like other routers)
- Modify: `backend/pareeksha/schemas/agents.py` (AgentCreate/AgentUpdate/AgentOut), `backend/pareeksha/api/routers/agents.py` (create/update/test-connection), `backend/pareeksha/runs/service.py` (refuse prompt agent with no active version)
- Test: `backend/tests/integration/test_prompt_versions_api.py`, `backend/tests/unit/agent_llm/test_url_guard.py`

**Interfaces — Consumes:** Task 1 schemas/table; `build_chat_provider` (Task 2); `integrations/crypto.py::SecretBox`.
**Produces:**
- `AgentCreate.endpoint_url` becomes optional only when `adapter == "prompt"` (model validator); server stores `prompt://<agent_id>`.
- `AgentCreate/AgentUpdate.adapter_secrets: dict[str, str] | None` — write-only (`exclude=True` / not on AgentOut), encrypted with `SecretBox` into `agents.adapter_secrets_encrypted`; update with `{}` clears. Key used by the runner: `"api_key"`.
- `AgentOut.has_adapter_secrets: bool`. `AgentOut` must not expose `adapter_secrets` (it currently subclasses AgentCreate — restructure so it can't).
- Routes (all under the agents project dependency; 404 for other tenants' agents; 409 `not_a_prompt_agent` when `adapter != "prompt"`):
  - `POST /agents/{agent_id}/prompt-versions` body `PromptVersionCreate` → 201 `PromptVersionOut` (version = max+1); if `content_hash` equals the active version's hash → 200 with the existing version. Sets `agents.adapter_config["active_version_id"]` and replaces `agents.expected_tools` with `[{name, description, args_schema: parameters}]`.
  - `GET /agents/{agent_id}/prompt-versions` → `list[PromptVersionOut]`, newest first.
  - `GET /agents/{agent_id}/prompt-versions/{version}` → `PromptVersionOut`.
  - `POST /agents/{agent_id}/prompt-versions/{version}/activate` → `PromptVersionOut` (updates pointer + expected_tools).
- Call `check_base_url` (Task 2) on version create/activate; violations → 422 `base_url_not_allowed`.
- `POST /agents/{agent_id}/test-connection` for prompt agents: one `chat` with the active version's system prompt and user message `"Hello"`, no tools; returns the existing response shape with ok/latency/error.
- Run creation for a prompt agent with no `active_version_id` → 422 `prompt_agent_has_no_version`.

- [ ] **Step 1: Failing tests** (integration, `api` + `tenant` fixtures): `test_create_prompt_agent_without_endpoint`, `test_create_version_sets_active_and_expected_tools`, `test_identical_version_is_not_duplicated`, `test_versions_listed_newest_first`, `test_activate_older_version`, `test_other_tenant_gets_404`, `test_versions_rejected_for_voice_agent` (409), `test_api_key_never_returned` (create with `{"api_key": "sk-test-secret"}`; assert the literal is absent from create/get/list/run `agent_snapshot` response bodies and `has_adapter_secrets is True`), `test_private_base_url_rejected` (`http://169.254.169.254/` and `http://127.0.0.1:8080` → 422), `test_run_refused_without_version`.
- [ ] **Step 2: Run** `python -m pytest tests/integration/test_prompt_versions_api.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; `python -m pytest tests/contract -q` still PASS; ruff + mypy clean.
- [ ] **Step 5: Commit** `feat(api): prompt versions, write-only agent secrets, base URL guard`.

### Task 4: Tool-call checks

**Files:**
- Modify: `backend/pareeksha/evaluation/checks.py` (`check_tool_calls` ~273, `run_checks` ~504), `backend/pareeksha/evaluation/evaluator.py:32` (dimension map)
- Test: `backend/tests/unit/evaluation/test_tool_checks.py` (or the existing checks test file if one covers `check_tool_calls`)

**Interfaces — Produces:**
- Expected entry may carry `"expect": "not_called"`: passes when no actual call has that name.
- `check_no_unexpected_tool(expected: Iterable[Mapping] | None, actual: Iterable[Mapping | ToolCall] | None) -> list[CheckResult]` with `check_type="no_unexpected_tool"`: runs only when `actual is not None` and `expected` is non-empty; one failing result per actual call whose name is not among expected names (excluding `not_called` entries); otherwise one passing result. Included by `run_checks`; mapped to the `tool_selection` dimension.

- [ ] **Step 1: Failing tests:** `test_not_called_passes_when_absent`, `test_not_called_fails_when_called`, `test_unexpected_tool_fails`, `test_no_unexpected_when_all_expected`, `test_unexpected_check_skipped_without_trace` (actual None → no result), `test_unexpected_check_skipped_without_expectations`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the new tests plus `python -m pytest tests/evaluation tests/judge -q` → PASS.
- [ ] **Step 5: Commit** `feat(eval): not_called expectations and no_unexpected_tool check`.

### Task 5: Text runner and simulator hook

**Files:**
- Create: `backend/pareeksha/simulation/text_runner.py`
- Modify: `backend/pareeksha/simulation/store.py::read_spec` (41-112), `backend/pareeksha/workers/simulator.py::_run_call` (140)
- Test: `backend/tests/unit/simulation/test_text_runner.py`

**Interfaces — Consumes:** `CallSpec`, `CallResult`, `TurnRecord`, `ToolCallRecord`, `CallEvent` (`simulation/models.py`); the caller source object `_call_runner()` passes to `CallRunner` (production `BrainCallerSource`; tests use `ScriptedCaller` from `tests/unit/simulation/simfakes.py`); Task 1 `PromptVersionOut`; Task 2 `ChatProvider`, `mock_result`.
**Produces:**
- `read_spec`: when `adapter == "prompt"`, resolve the version id from the request's run `test_runs.agent_snapshot["adapter_config"]["active_version_id"]` (fallback: `agents.adapter_config`), load that `prompt_versions` row into `AgentTarget.adapter_config["prompt_version"]` (JSON dict of `PromptVersionOut`), and decrypt `adapter_secrets_encrypted` with `SecretBox` into `AgentTarget.adapter_secrets`.
- `async def run_text_call(spec: CallSpec, *, caller: <caller source type>, chat: ChatProvider, clock: Callable[[], float] = time.monotonic) -> CallResult` — reads the version from `spec.agent.adapter_config["prompt_version"]`.
- `_run_call`: if `spec.agent.adapter == "prompt"`: build provider via `build_chat_provider(version.provider, api_key=spec.agent.adapter_secrets.get("api_key"), base_url=version.base_url)` after `check_base_url`, return `(await run_text_call(...), {})`. Same crash → `infra_error` handling as today.

**Loop (decided):**
1. Messages start `[system]`. The caller always speaks first in text mode (ignore `caller_speaks_first=False`; event `caller_first_text_mode`).
2. Each round: caller utterance → caller `TurnRecord`; if the caller ends the call, end with the same `EndReason` `CallRunner` uses for a caller-ended call. Then agent: up to `max_tool_rounds` `chat` calls; each tool call → `mock_result(tool, args, override=<scenario expected entry's "mock_result" for that tool name, if any>, simulate=<one chat call to the same provider asking for a JSON result>)`, `ToolCallRecord(seq, name, arguments, result, at_ms, turn_idx=<agent turn idx>)`, appended as a tool message. Text reply → agent `TurnRecord` (`glass_box_text` = text). Rounds exhausted with tools still requested → event `tool_round_limit`, end `agent_silent`.
3. Stop at `scenario.max_turns` caller turns → `max_turns`; wall clock over `spec.max_call_seconds` → `timeout`.
4. `AgentLLMError` before any agent turn → `connect_failed`, after → `infra_error`; `error` = `str(exc)`.
5. Each chat call adds `CallEvent(type="agent_llm_usage", data={input_tokens, output_tokens, latency_ms, model})`. `glass_box=True`. Times are ms from start via `clock`.

- [ ] **Step 1: Failing tests** with a scripted fake `ChatProvider` and `ScriptedCaller`: `test_plain_conversation_records_turns`, `test_tool_call_recorded_with_mock_result`, `test_scenario_mock_override_used`, `test_tool_round_limit_ends_agent_silent`, `test_invalid_arguments_continue_call`, `test_provider_error_first_turn_connect_failed`, `test_provider_error_later_infra_error_without_key` (key string absent from `error`), `test_max_turns`, `test_caller_end_call`, `test_usage_events_recorded`.
- [ ] **Step 2: Run** `python -m pytest tests/unit/simulation/test_text_runner.py -q` → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS, plus `python -m pytest tests/unit/simulation -q` unchanged-green.
- [ ] **Step 5: Commit** `feat(sim): text runner for prompt agents`.

### Task 6: Prompt-aware scenario generation and judge context

**Files:**
- Modify: `backend/pareeksha/workers/generator.py` (~100-116), `backend/pareeksha/evaluation/pg_stores.py` (where `AgentInfo` is built)
- Test: `backend/tests/unit/test_generator_worker.py` (extend), judge input test near `pg_stores` usage

**Produces:** helper `def prompt_context(description: str, version: Mapping[str, Any] | None) -> str` (in `pareeksha/agent_llm/context.py`) returning `description` unchanged when `version` is None, else `description + "\n\nSystem prompt under test:\n" + version["system_prompt"]`. Generator passes it as `AgentBrief.description` for prompt agents (tools already come from the synced `expected_tools`); `pg_stores` passes it as `AgentInfo.description` for prompt agents, using the version pinned by the call's run.
- [ ] Steps: failing tests `test_prompt_agent_brief_includes_system_prompt`, `test_voice_agent_brief_unchanged`, `test_judge_agent_info_includes_pinned_prompt` → implement → pass → commit `feat(prompt): system prompt in scenario generation and judge context`.

### Task 7: Version-aware compare

**Files:** Modify `backend/pareeksha/runs/compare.py` (cell_results 42-61, compare_runs 103-118), `backend/pareeksha/schemas/runs.py` (`RunCompareOut`, `RunCompareCell`). Test: extend the existing compare test.
**Produces:** `RunCompareOut.base_prompt_version: int | None`, `head_prompt_version: int | None` (from each run's `agent_snapshot.adapter_config.active_version_id` → `prompt_versions.version`); `RunCompareCell.base_call_ids: list[UUID]`, `head_call_ids: list[UUID]`. Cell key unchanged.
- [ ] Steps: failing tests `test_compare_reports_prompt_versions`, `test_compare_cells_carry_call_ids`, `test_voice_compare_versions_null` → implement → pass → commit `feat(runs): prompt versions and call ids in run compare`.

### Task 8: SDK and CLI

**Files:** `sdk/python/src/pareeksha_sdk/` (models.py `adapter` literal add `"prompt"`; client methods; CLI module). Tests under `sdk/python/tests` following existing style.
**Produces:** `Client.create_prompt_version(agent_id, **PromptVersionCreate fields) -> dict`, `Client.list_prompt_versions(agent_id) -> list[dict]`, `Client.activate_prompt_version(agent_id, version) -> dict`. CLI: `pareeksha prompt push --agent NAME --file PROMPT.md --provider P --model M [--tools tools.json] [--temperature T] [--base-url URL] [--note TEXT]` (prints version number; "unchanged" when the server returns the existing version) and `pareeksha prompt versions --agent NAME`. Existing `pareeksha run --agent NAME ...` works for prompt agents unchanged.
- [ ] Steps: failing tests against a mocked HTTP layer (existing SDK test pattern) → implement → pass → commit `feat(sdk): prompt version commands`.

### Task 9: Web UI

**Files:** `web/components/agents/agent-form.tsx` (46, 186), `web/components/agents/agents-list.tsx:189`, `web/app/agents/[id]/page.tsx`, new `web/components/agents/prompt-versions.tsx`, `web/app/runs/compare/page.tsx`, regenerated `web/lib/api/schema.d.ts` (`npm run gen:api`), `web/tests/support/mock-api.ts`, `web/tests/agents.spec.ts`.
**Produces:** adapter option "Prompt (text)"; when chosen, endpoint URL hidden; provider select, model, base URL, API key (password input, write-only, shows "key saved" from `has_adapter_secrets`), system prompt editor, temperature, max tool rounds, tools editor (JSON textarea validated client-side against `PromptTool` shape, per-tool mock). Agent page: versions list (number, note, date, active badge), view a version, line diff between two selected versions, "Save as new version", "Activate". Compare page: "v{base} → v{head}" header and per-cell links opening both calls. Call page already shows tool calls if glass-box events exist; verify and show them inline for text calls.
- [ ] Steps: playwright smoke tests in `agents.spec.ts` for creating a prompt agent and saving a version (mock API) → implement → `npm run lint && npx tsc --noEmit && npm run gen:api:check && npm run test:smoke` → commit `feat(web): prompt agents, versions and diff`.

### Task 10: End-to-end test and docs

**Files:** `backend/tests/integration/test_prompt_agent_e2e.py`; `docs/06-api-spec.md` (new routes); new `docs/guides/09-prompt-testing.md`; README guides table row.
- [ ] e2e: create prompt agent + version with one tool (`static` mock) via API, create a scenario with `expected_tool_calls=[{"name": "lookup_emi"}, {"name": "waive_fee", "expect": "not_called"}]`, drive `on_call_requested` with `build_chat_provider` monkeypatched to a scripted fake and a scripted caller, then run the evaluator path; assert `turns`, `tool_calls` rows and check results `tool_calls_expected` passed, `no_unexpected_tool` passed. Second version whose fake calls `waive_fee` → that check fails; compare shows v1→v2 and the newly failing cell.
- [ ] Guide: create agent, push version from CLI, generate scenarios, run text, compare versions.
- [ ] Commit `test(prompt): end-to-end prompt agent run; docs: prompt testing guide`.

## Execution order

Task 1 → (Tasks 2, 4 in parallel) → (Tasks 3, 5, 6, 7 in parallel) → (Tasks 8, 9, 10 in parallel) → whole-branch review + security audit (secrets, URL guard, tenant scoping).
