# Prompt testing and RAG testing: design

Date: 2026-11-06. Status: approved by owner 2026-11-06 (with the local-only switch).

## Why

Customers run an LLM every day on a system prompt. They change that prompt in small ways and
today have no way to know, before shipping, how the agent's behaviour changes: does it still say
the right thing, does it still call the right tool, does it start making things up. Many of them
also add retrieval (RAG) and cannot tell which retrieval method suits their data, whether RAG
actually stops hallucination, how much latency it adds, or how much money it saves compared with
pasting the whole knowledge base into the prompt.

Pareeksha already has the pieces for voice bots: a scenario generator (test cases), a caller
brain (simulated user), a judge, tool-call recording and run compare. This feature points those
pieces at a **prompt** instead of a deployed voice bot, and adds a **RAG lab** on top.

## What the owner asked for (their words, condensed)

- Give the prompt the LLM uses every day; another agent creates the test cases; test the prompt,
  including how it handles the user's replies (multi-turn).
- After a small prompt change, see how the agent behaves, and whether tool calls happen or not.
- RAG testing: try the most-used RAG methods so customers can pick the one for their project;
  test with and without RAG to see whether it hallucinates; see how knowledge is retrieved;
  retrieval latency; cost, and how much RAG saves.
- Works both as a text "prompt method" and through a (voice) call.
- Embeddings: local by default, Gemini optional, and API support for all the major providers so
  customers can bring their own.
- Everything usable through the API too.

## Goals

1. **Prompt agents.** A new agent kind whose definition is: system prompt, model (provider +
   model id), declared tools (with mock behaviour), optional RAG config. Versioned: every edit of
   the prompt/model/tools/RAG config is a new immutable version.
2. **Test cases generated from the prompt.** The existing scenario generator reads the system
   prompt and declared tools (and, when RAG is on, the knowledge base) and drafts happy-path,
   edge-case and adversarial scenarios with expected tool calls. Owner reviews/accepts drafts as
   today.
3. **Text runs.** A run against a prompt agent with `mode=text` plays each scenario as a typed,
   multi-turn conversation: caller brain ↔ the prompt on the chosen model. No audio, no Gnani,
   runs in parallel (bounded by provider rate limits), seconds per scenario.
4. **Call runs.** The same prompt agent with `mode=call` is served behind Pareeksha's own STT/TTS
   (like `mock_agent`), so the existing voice simulator, personas and noise profiles test it end
   to end. Tool calls and retrievals surface as glass-box events.
5. **Tool-call testing.** For every turn, record each tool call (name, arguments, mock result,
   latency). Judge checks per scenario: expected tool called, arguments match (exact or
   LLM-judged semantic match), no unexpected tool called, call order when the scenario says so.
6. **Version compare.** Run v1 and v2 of a prompt on the same scenarios and show what changed:
   scores, newly failing / newly passing scenarios, tool-call differences, side-by-side
   transcripts. Reuses `runs/compare.py`.
7. **RAG lab.**
   - Knowledge bases: upload documents (txt, md, pdf, docx, html, csv), chunk, embed once, store.
   - Retrieval methods (the commonly used set):
     - keyword: BM25
     - dense vector: cosine top-k
     - hybrid: BM25 + vector fused with reciprocal rank fusion (RRF)
     - hybrid + reranker (cross-encoder)
     - MMR (diversified dense top-k)
     - query rewriting: multi-query and HyDE
     - small-to-big / parent-document (retrieve small chunks, send their parent section)
   - Chunking strategies: fixed-size with overlap, recursive (headings → paragraphs →
     sentences), sentence-window. Chunk size and overlap are parameters.
   - A **RAG matrix run**: the same scenarios against one prompt version under N retrieval
     configs plus two baselines: **no RAG** and **full-context stuffing** (whole KB in the
     prompt, when it fits the model's context window).
   - Retrieval inspector: for every turn, which chunks were retrieved, their scores, rank, and
     which method found them.
8. **RAG metrics per config.**
   - Retrieval: hit rate / recall@k, MRR, context precision (only for generated questions whose
     source chunk is known; see "Ground truth").
   - Generation: faithfulness / groundedness (claims in the answer supported by retrieved
     context, LLM-judged claim by claim), answer correctness vs reference answer, hallucination
     rate (share of answers with at least one unsupported factual claim), refusal correctness
     (said "I don't know" when the KB has no answer).
   - Latency: query-embedding ms, search ms, rerank ms, query-rewrite ms, total retrieval ms
     (p50/p95), plus model time-to-first-token and total turn latency.
   - Cost: embedding cost (one-time index build, and per-query), rerank cost, LLM input/output
     tokens and money per conversation; **savings** of each config vs full-context stuffing
     and vs no-RAG, in ₹ and %, projected to a customer-entered monthly conversation volume.
   - A recommendation line per matrix run: best config by a stated rule (highest faithfulness
     with recall above a floor, ties broken by cost then latency), shown with the numbers.
9. **Providers (bring your own key).** Stored encrypted like `adapter_secrets_encrypted`.
   - LLM under test: DeepSeek, Gemini, OpenAI, Anthropic, Azure OpenAI, AWS Bedrock, Mistral,
     Groq, Ollama, any OpenAI-compatible endpoint (vLLM, Together, OpenRouter, …). All with
     native tool calling.
   - Embeddings: local (default), Gemini, OpenAI, Azure OpenAI, Cohere, Voyage, Jina, Mistral,
     AWS Bedrock, Ollama, any OpenAI-compatible endpoint.
   - Rerankers: local cross-encoder (default), Cohere, Jina, Voyage.
   - Each provider has a price table entry (per 1M tokens, editable per project) used for cost.
10. **API, SDK, CLI.** Every action above is a REST endpoint (documented in
    `docs/06-api-spec.md`), exposed in the Python SDK and CLI
    (e.g. `pareeksha prompt run --agent "Support Bot" --version 3 --mode text --wait`,
    `pareeksha rag matrix --agent … --kb … --configs bm25,hybrid_rerank`), and usable from the
    existing GitHub Action so a prompt change in a PR is tested in CI.
11. **Web UI.** Pages for: prompt agent editor (prompt, model, tools, RAG settings, version
    history with diff), run results (transcript with tool-call and retrieval cards inline),
    version compare, knowledge bases, RAG matrix report (table + latency/cost charts).

## Non-goals

- Not a prompt optimiser: we test and compare, we do not rewrite the customer's prompt.
- No production RAG serving: the RAG lab exists to test; customers implement the winning method
  in their own stack. The report states the exact config so they can reproduce it.
- No managed vector database. No real tool execution against customer systems in this version
  (tools are mocked; see below).
- No fine-tuning, no training embeddings.
- No change to the frozen JSON-completion contract in `backend/pareeksha/llm/base.py`.

## Anti-goals (would be a failure even if it works)

- Prompt test results that are not reproducible: the same version + scenario + seed must give a
  comparable result; every run records prompt version hash, model id, temperature, retrieval
  config and KB index version.
- Silent cost: a run must show its estimated cost before it starts (existing estimate/budget
  flow) and its actual cost after.
- Customer documents or keys leaking across projects or into logs/briefs. All new tables are
  tenant-scoped like existing ones.
- A RAG "winner" declared on too few questions without saying so: the report shows the number of
  questions and confidence intervals, like the calibration report does.

## How it fits the existing system

- **Agents.** Add `prompt` to the `agents.adapter` check. A prompt agent's current definition
  lives in a new `prompt_versions` table (agent_id, version int, system_prompt, provider,
  model, temperature, tools JSON, rag_config JSON, content hash, created_by, created_at);
  `agents.adapter_config` points at the active version. `endpoint_url` is unused for prompt
  agents (make it nullable or store `prompt://<agent_id>`; builder's call).
- **Model-under-test providers.** New package `backend/pareeksha/agent_llm/` with one interface:
  `chat(messages, tools, model, temperature) -> reply text + tool calls + usage + latency`.
  Separate from `pareeksha/llm/` because that contract is frozen and JSON-only. Implement with
  `httpx` (already installed), no vendor SDKs: one OpenAI-compatible client covers OpenAI,
  Azure, Groq, Mistral, DeepSeek, Ollama, vLLM and other compatible endpoints; native clients for
  Anthropic and Gemini; Bedrock through its OpenAI-compatible endpoint with a Bedrock API key
  (builder verifies this endpoint and its tool-calling support; fall back to Converse API with
  SigV4 only if needed).
- **Tools.** Declared per prompt version as JSON Schema (OpenAI function format). Each tool has a
  mock mode: `static` (fixed JSON result), `by_args` (table of argument patterns → results), or
  `simulated` (an LLM produces a plausible result from the tool description and the scenario).
  The scenario can override mock results (e.g. "payment API returns error").
- **Text run loop.** New runner in `simulation/` (e.g. `text_runner.py`) used by the simulator
  worker when the agent is a prompt agent and the run's mode is `text`: caller brain produces
  the user turn, the agent LLM replies (looping on tool calls with mock results, max tool rounds
  configurable), until the scenario's `max_turns`, a hang-up intent, or a loop is detected.
  Writes the same `calls`, turns and `tool_calls` rows the voice path writes, so the evaluator,
  judge, finalizer, compare, HubSpot/webhook sinks work unchanged. A new call field records
  `mode` (`text`/`call`) and, for RAG, per-turn retrieval rows.
- **Call run.** A `prompt` adapter implements `AudioSession` by running the same agent loop
  behind Pareeksha's STT/TTS (the pattern `mock_agent` already uses), emitting `AgentToolCall`
  glass-box events, so the existing simulator is untouched.
- **Scenario generation.** Extend `AgentBrief` with the system prompt text, declared tools and
  (when RAG is on) a sample of KB chunks; new prompt template version. RAG scenarios include
  questions answerable from a specific chunk (ground truth), questions the KB cannot answer
  (should refuse), and questions needing two chunks.
- **Judge.** Existing rubric checks keep working (`tool_calls_expected`, `forbidden_absent`,
  etc.). Add checks: `tool_args_match`, `no_unexpected_tool`, `grounded_in_context`
  (faithfulness), `answer_correct`, `refused_when_unknown`. They go into the rubric like the
  existing checks, so calibration tooling still applies.
- **RAG storage.** New tables: `knowledge_bases`, `kb_documents`, `kb_chunks` (text, parent
  id, position, chunking config id), `kb_embeddings` (chunk id, embedding model id, vector),
  `retrievals` (call turn, config, chunk ids, scores, ms per stage). Embeddings are computed
  once per (chunk, embedding model) and reused across runs; only changed documents are
  re-chunked and re-embedded.
- **Vector search.** Vectors stored as `real[]` and searched in-process with numpy (installed)
  — enough for test-sized KBs (tens of thousands of chunks). ponytail: brute force; switch the
  Postgres image to pgvector when a customer KB outgrows it. BM25 via Postgres full-text search
  (`tsvector`, `simple` config so Hindi/Kannada tokens are kept) or an in-process BM25; builder's
  call, measured on the Indic sample.
- **Local models.** Embeddings and reranker run in-process via ONNX (e.g. `fastembed`, no
  PyTorch) with a multilingual model so Hindi, Kannada and Hinglish work — default candidates
  `intfloat/multilingual-e5-large` (embeddings) and a multilingual cross-encoder for reranking.
  Builder confirms the package and model names exist and their licences allow commercial use,
  and pins versions. Models download once into a Docker volume.
- **Runs and compare.** `test_runs` gains `mode` and, for matrix runs, a `rag_config_id` per run
  item, so a RAG matrix is one run with items per (scenario × config). Version compare reuses
  `runs/compare.py` with the cell key extended by prompt version / RAG config.
- **Cost.** Reuse `api_usage` logging; extend with `purpose` values for agent LLM, embeddings and
  rerank, and a provider price table. Estimates flow through the existing `runs/estimate.py`
  budget check.

## Settled details (designer's calls after builder review)

- **KB scope and reproducibility.** A knowledge base belongs to a project and can be attached to
  any prompt version of any agent in it. Every (re)index creates a new immutable
  `kb_index_version` (documents + chunking config + embedding model); old versions are kept
  until deleted. `prompt_versions.rag_config` names the KB; each run pins the exact
  `kb_index_version` it used. Compare shows a "KB changed" banner when v1 and v2 runs used
  different index versions.
- **Text runs in the run matrix.** A `run_items` CHECK cannot see its parent run's mode, so the
  text/noise invariant is enforced in the run service and planner, not by a table constraint. As
  built, `run_items.noise_profile_id` stays NOT NULL: the simulator plays every item of a prompt
  agent (`adapter = "prompt"`) as text, and the item's noise profile is recorded but not applied.
  If the column later becomes nullable (null = text mode), the planner sets and checks it.
  Personas still apply in text mode as caller style
  and language. RAG matrix adds nullable `run_items.rag_config_id` to the unique key; the planner
  and the compare cell key gain prompt version and RAG config.
- **Judge, caller and comparability.** Caller brain, judge and claim-level faithfulness checks
  use the project's configured Pareeksha LLM (DeepSeek by default), the same as today. Cost is
  estimated before start through `runs/estimate.py` and the existing budget check; a matrix run
  defaults to at most 4 configs + 2 baselines. "Comparable" means everything that affects output
  is recorded and the run supports `repeats` per cell (default 1, recommend 3 for decisions);
  the report shows spread when repeats > 1. Provider nondeterminism is not hidden.
- **Tool-call expectations.** Each entry of `scenarios.expected_tool_calls` gains
  `match: "exact" | "semantic"` (default exact, semantic is LLM-judged) and optional
  `mock_result` overriding the tool's mock for that scenario. No new scenario column for tools.
- **RAG ground truth on scenarios.** New nullable scenario JSON column `rag_expectation`:
  `{source_document_id, source_span: [start, end], reference_answer, answerable: bool}`.
  Ground truth is tied to a **document span**, not a chunk id, so it survives re-chunking: a
  retrieved chunk is a hit when it overlaps the span. Ground-truth CSV columns: `question,
  expected_answer, source_document, source_quote` (quote located in the document to get the
  span; rows whose quote is not found are reported, not silently dropped).
- **Chunking is a matrix dimension.** A RAG config = chunking config + retrieval method +
  parameters. Each distinct chunking config needs its own index (embedded once, reused).
  Because ground truth is span-based, recall@k and MRR stay comparable across chunkings.
- **Call mode.** The `prompt` adapter runs in-process in the simulator worker and receives
  decrypted provider keys through `AgentTarget.adapter_secrets`, as other adapters do. RAG
  matrix runs default to text mode; call mode is allowed and reports retrieval latency
  separately from audio/STT/TTS latency.
- **Savings baseline.** Token counts come from provider-reported usage; where a provider reports
  none, an estimate (characters / 4) is used and labelled "estimated". Full-context stuffing is
  shown as "n/a: KB does not fit the model's context window (N tokens vs limit M)" when it does
  not fit; never truncated. Monthly conversation volume is an input on the matrix report (per
  view, not stored), defaulting to 10,000.
- **Local-only knowledge bases (owner decision).** Each knowledge base has a `local_only`
  switch (default off). When on, no text from its documents or chunks leaves the Pareeksha
  deployment: embeddings and reranking must use local models; scenario generation, the judge's
  faithfulness/correctness checks and the caller brain only get KB text if the project's
  Pareeksha LLM is a local provider (Ollama or a self-hosted OpenAI-compatible endpoint the
  owner has marked local), otherwise those steps are refused with a clear error naming the
  switch. The prompt-under-test model is also checked: a run that would send retrieved chunks to
  a hosted model is refused. Enforced server-side in one place (a guard every provider call for
  that KB goes through), not in the UI, and covered by tests. Switching it on for an existing KB
  does not delete anything already sent; the UI says so.
- **Migration.** `agents.endpoint_url` stays NOT NULL; prompt agents store
  `prompt://<agent_id>`. The adapter CHECK gains `prompt`. Price table seeded from providers'
  public pricing at build time with the date recorded; editable per project.

## Ground truth for RAG metrics

Retrieval metrics need to know the right chunk. The test-case agent generates questions from
specific chunks (so the source chunk id and a reference answer are stored with the scenario),
and customers can also upload their own question / expected-answer / source-document sets
(CSV). Metrics that need ground truth are computed only for those questions; faithfulness and
hallucination need no ground truth and are computed for every answer.

## Build order (phases)

1. Prompt agents + versions, agent-LLM providers (start: OpenAI-compatible, Anthropic, Gemini,
   DeepSeek), mocked tools, text runner, judge tool checks, version compare, API/CLI, web pages.
2. Remaining LLM providers (Azure, Bedrock, Ollama specifics), call-mode `prompt` adapter.
3. RAG lab: knowledge bases, chunking, local embeddings, BM25 / vector / hybrid / rerank,
   retrieval inspector, faithfulness + hallucination checks, no-RAG and full-context baselines.
4. RAG methods MMR, multi-query, HyDE, small-to-big; remaining embedding/rerank providers;
   matrix report with latency, cost, savings and recommendation; GitHub Action support.

Each phase ships with tests and leaves the existing voice flow green.

## Decided by the owner

- Embeddings local by default, Gemini optional, all major providers supported via API key.
- Both text ("prompt method") and call modes.
- With/without-RAG comparison, retrieval latency, cost and savings are required.
- Each knowledge base has a "local only" switch that keeps its documents away from outside
  services.

## Calls made by the designer (owner to check)

- Prompt agent as a new agent adapter rather than a separate product area, so the whole existing
  pipeline (scenarios, judge, compare, sinks, CI) applies for free.
- Separate provider layer for the model under test instead of changing the frozen LLM contract.
- Tools are mocked, not executed.
- numpy brute-force vector search instead of adding pgvector now.
- The list of RAG methods and chunking strategies above.
- Recommendation rule: faithfulness first, recall floor, then cost, then latency.
- Phase order above (prompt testing before RAG).

## Left to the builder

Exact table/column names, endpoint paths (following `docs/06-api-spec.md` conventions), web page
layout within the existing design system, BM25 implementation, PDF/docx parsing library choice
(prefer installed or stdlib; name any new dependency in the plan), prompt template wording,
concurrency limits for text runs.
