# Guide 10 · Test retrieval (RAG) before you ship it

Goal: find out which retrieval setup (chunking, embedding model, search method) makes your prompt agent answer correctly from your own documents, and what it costs. You upload documents to a **knowledge base**, build **indexes**, add questions with known answers, and run a **matrix**: several retrieval configs plus two baselines on the same questions. The report shows hit rate, hallucination rate, latency and cost side by side.

**Prerequisite:** [Guide 9](09-prompt-testing.md) (a prompt agent with a pushed version), the CLI with `PAREEKSHA_API_KEY` set, and the stack running with the `indexer` worker (it is part of `docker compose up`).

## 1. Create a knowledge base and upload documents

```bash
pareeksha kb create faq --local-only      # --local-only is optional, see section 5
pareeksha kb upload --kb faq refunds.pdf delivery.md policies.docx
```

Supported files: txt, md, html, csv, json, pdf, docx. Each file may be up to 10 MiB. A knowledge base holds at most 200 documents and 2,000,000 extracted characters. Uploading the same file twice changes nothing. A file with no extractable text (for example a scanned PDF) is rejected.

Over the API: `POST /knowledge-bases`, then `POST /knowledge-bases/{id}/documents` with the file as multipart form data.

## 2. Build an index

An index is the documents cut into chunks and embedded. It is versioned: the same chunking and embedding model on the same documents gives the same index, and Pareeksha returns the existing one instead of building it again. Chunks that did not change are reused across builds, so a small edit is cheap.

```bash
pareeksha kb index --kb faq --strategy recursive --size 400 --overlap 50 --wait
pareeksha kb index --kb faq --strategy fixed --size 800 --overlap 0 --wait
```

The default embedding model is `local:intfloat/multilingual-e5-large`. Pass `--embedding provider:model` to use a hosted one, and set its key with `pareeksha kb create --embedding-key-env VAR` or `pareeksha kb set-keys`. Keys are write-only: stored encrypted, never returned.

**Ollama.** To embed with a model on your own Ollama server (for example `qwen3-embedding:0.6b`, 1024 dimensions, multilingual), run Pareeksha's Ollama container:

```bash
docker compose --profile ollama up -d    # starts `ollama` and pulls OLLAMA_PULL (default qwen3-embedding:0.6b)
```

It runs as its own container with its models in the `ollama-models` volume. It is not published on the host, so only the stack can reach it. Compose points `OLLAMA_BASE_URL` at it (`http://ollama:11434/v1`); for an Ollama installed on the host, set `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` in `.env` instead. Then, in the web app, choose provider `ollama` in **Build index** and enter the model name. The endpoint field can stay empty (it means `OLLAMA_BASE_URL`). On the CLI:

```bash
pareeksha kb index --kb faq --embedding ollama:qwen3-embedding:0.6b --wait
```

That one server is trusted without `AGENT_LLM_ALLOW_PRIVATE_URLS`, and it counts as local, so a local-only knowledge base may embed with it. Use the same embedding in the RAG config of the prompt version or matrix, since runs embed each question with it.

**Endpoints and keys in the app.** For `openai_compatible`, `azure_openai` and `bedrock`, **Build index** and the RAG settings have an **Endpoint** field; Pareeksha checks it when you build (https on a public address, `422 base_url_not_allowed` otherwise; a private server needs `AGENT_LLM_ALLOW_PRIVATE_URLS`). API keys for hosted embedding models and rerankers go in **Provider keys** on the knowledge base page. They are write-only: stored encrypted, shown only as "keys saved", and you can replace or clear them. The key for Pareeksha's own LLM (the caller and judge, for example DeepSeek) is under **Settings → LLM**.

**Chunking trade-offs.**

- Small chunks (200 to 400 characters) find the exact sentence and keep the prompt short, but a fact that spans two paragraphs gets cut in half.
- Large chunks (800 or more) keep context together, but each hit carries more unrelated text, which costs tokens and can distract the model.
- Overlap (about 10 to 15 percent of the size) protects facts at a boundary. More than that mostly duplicates text.
- `fixed` cuts at a character count and is the most predictable. `recursive` prefers paragraph, then sentence boundaries and is a good default. `sentence_window` embeds single sentences and returns their neighbours (`window`), which suits short factual answers.
- Build two or three indexes and let the matrix decide. The chunk browser (`GET /knowledge-bases/{id}/indexes/{index_id}/chunks`, or the index page in the web app) shows exactly what was cut.

## 3. Add questions with known answers

Retrieval can only be scored against a known source. Two ways:

```bash
pareeksha kb questions import --kb faq --agent refund-bot questions.csv
pareeksha kb questions generate --kb faq --agent refund-bot --count 20 --unanswerable-share 0.2
```

The CSV has four columns: `question`, `expected_answer`, `source_document` (the filename), `source_quote` (text copied from that document). Pareeksha finds the quote in the document and stores its position; a quote it cannot find is reported as unmatched and skipped. A row with an empty `source_quote` means the knowledge base does not answer it, and the agent should say so. Include some of these: they catch an agent that makes things up.

Generated questions are drafted by the platform LLM from your document text and each quote is checked against the document. Generation is refused for a local-only knowledge base. Review the drafts in the web app before you save them; the imported or saved questions become scenarios tagged `rag`.

In the web app, both are on the knowledge base page under **Questions**. The panel lists the questions on this knowledge base's documents plus every unanswerable one. **Generate** shows the drafts for review; untick the ones you do not want. **Import CSV** offers an example file with the four columns, reports how many questions were created, and lists every skipped row with its reason.

You need at least 10 questions with a known source before the report will recommend a config, and 30 or more before the confidence intervals are useful.

## 4. Run the matrix

Write a config file, a list of up to four retrieval configs:

```json
[
  {"kb_id": "…", "label": "bm25-400", "method": "bm25", "top_k": 3,
   "chunking": {"strategy": "recursive", "size": 400, "overlap": 50}},
  {"kb_id": "…", "label": "hybrid-800", "method": "hybrid", "top_k": 5,
   "chunking": {"strategy": "fixed", "size": 800, "overlap": 0}}
]
```

```bash
pareeksha rag run --agent refund-bot --kb faq --config configs.json --wait
```

This prints the matrix id. Every config needs a ready index with the same chunking and embedding; if one is missing the API answers `409 rag_index_missing` and lists which, and nothing is created. Unless you pass `--no-baselines`, two baselines run on the same questions:

- **No RAG**: the agent answers from its prompt alone. It shows how much retrieval helps and how often the model makes things up unaided.
- **Full context**: the whole knowledge base is put in the prompt. It is the accuracy ceiling and the cost ceiling. If the knowledge base is longer than the config's `context_char_limit` (default 400,000 characters) this row says `n/a` instead of running.

Each entry is an ordinary run, so you can open its calls, see what was retrieved for every turn, and compare any two with `GET /runs/compare` (or Runs, select two, Compare).

### The search methods

| Method | What it is | Use it when |
|---|---|---|
| `bm25` | keyword matching | questions use the exact words, product names, codes or IDs that appear in the documents |
| `dense` | embedding similarity | people paraphrase, or ask in Hindi or Kannada about English documents |
| `hybrid` | bm25 and dense, merged | a good default; start here |
| `hybrid_rerank` | hybrid, then a reranker re-orders the top candidates | precision matters more than a little extra latency |
| `mmr` | dense, but penalises near-duplicate chunks (`mmr_lambda`) | the documents repeat themselves |

Options on top of a method:

- `query_transform: "multi_query"` asks the agent's model for a few rewrites of the question; `"hyde"` has it write a hypothetical answer and searches with that. Both help with vague questions and cost an extra model call per turn. `hyde` needs a method that uses embeddings.
- `small_to_big: true` searches small chunks but puts the larger surrounding section in the prompt. Use it when answers need the paragraph around the sentence.
- `top_k` is how many chunks reach the prompt. `candidate_k` is how many the search considers before reranking.

### The `{{context}}` placeholder

Put `{{context}}` in the agent's system prompt where the retrieved text should go. Without it, Pareeksha appends the text at the end under a "Retrieved context:" heading. Runs without retrieval (the No RAG baseline) replace `{{context}}` with nothing. The matrix tests the agent's **active** prompt version by default. To test another one, pass its number as `prompt_version` on `POST /rag-matrices` (or pick it in the web form): any existing version works, active or not, and every run of the matrix executes that version. The agent's active version does not change. An unknown number is `404 not_found` with `{"version": n}`.

## 5. The local-only switch

A knowledge base created with `--local-only` (or `local_only: true`, changeable later with `PATCH /knowledge-bases/{id}`) promises that its text never leaves your machines. Pareeksha enforces it in one place and it does three things:

- Embedding and reranking must use `local` models. A hosted embedding config is rejected when you build the index or start the matrix.
- The model under test must be a local endpoint (for example Ollama on a private address). A hosted agent model is refused, because it would receive the retrieved text.
- The platform LLM (DeepSeek or Gemini) never sees the text. Question generation from the knowledge base is refused. Because a test run sends the agent's answers (built from your text) to Pareeksha's hosted LLM, which plays the simulated caller and judges the call, **test runs and matrices on a local-only knowledge base are disabled** (`409 local_only`, with or without RAG) until a local Pareeksha LLM is configured. A run created earlier is stopped at call start if you switch the flag on afterwards (`connect_failed`, error `local_only`), and the rubric judge skips such a call (review reason `local_only`).

Upload, index builds and chunk browsing still work, and importing your own questions works. Use it for documents you may not send to a third party.

## 6. Read the report

```bash
pareeksha rag report <matrix-id> --monthly 10000
pareeksha rag report <matrix-id> --json
```

Or `GET /rag-matrices/{id}/report?monthly_conversations=10000`. One row per entry:

- **n**: `n_questions_with_truth` is how many questions with a known source were scored; `n_calls` is how many calls ran. Read every rate with n beside it. Two questions can show 100 percent and mean almost nothing.
- **Hit rate (with CI)**: the share of questions where a retrieved chunk overlaps the true source passage. The interval is a 95 percent Wilson interval; if two configs' intervals overlap, you cannot tell them apart yet. **MRR** rewards the right chunk being ranked first. **Context precision** is the share of retrieved chunks that were the right ones.
- **Generation**: **faithfulness** is the share of the answer's claims supported by the retrieved text. **Hallucination rate** is the share of answers with at least one unsupported claim. **Answer correct** and **refusal correct** compare against your expected answer and the answerable flag. These come from an LLM judge, so treat them as strong evidence, not proof. `skipped` counts metrics that could not be computed and why (`no_ground_truth`, `no_evidence`, `local_only`, `judge_error`).
- **Latency**: median and 95th percentile retrieval time (split into embed, search, rerank, rewrite) and the agent's turn time.
- **Tokens and cost**: tokens per conversation (agent input and output, query embedding, rerank) are always shown. Cost in rupees is shown only for models that have a price (next section); an unpriced model leaves the cost blank rather than guessing. **Index one-time** is the cost of embedding the knowledge base once.
- **Savings**: against Full context and against No RAG, as rupees and percent per month at `--monthly` conversations, plus `token_savings_vs_full_context_pct`, which needs no prices.
- **Recommendation**: the label of the best config, or `null` with a reason. A config qualifies with at least 10 questions with a known source and a hit rate of 70 percent or more; the winner has the highest faithfulness, then the lowest cost, then the fastest retrieval. With fewer questions it says, for example, "not enough ground-truth questions (2 < 10)".

## 7. Enter prices

Pareeksha ships no price list: a wrong built-in price is worse than a blank one, and local models cost 0. Enter your provider's current prices in rupees per million tokens, per project:

```bash
pareeksha rag pricing                                  # prices set, and models still unpriced
pareeksha rag set-price --kind llm --provider openai --model gpt-4o-mini \
  --input-per-m 12.5 --output-per-m 50
```

Over the API, `GET /pricing` returns `{prices, unpriced}` and `PUT /pricing` replaces entries (a list of `{kind, provider, model, input_per_m_inr, output_per_m_inr}`; `kind` is `llm`, `embedding` or `rerank`; embeddings and rerankers have no output price). A `local` embedding or reranker cannot be priced. Reports pick up new prices immediately, with no re-run.

## Limits

- The search index is built in memory per run worker. BM25 and dense search are fine up to about 50,000 chunks; beyond that move the search into the database.
- The CLI's `pareeksha rag run` always tests the active prompt version; use the API's `prompt_version` (or the web form) for another one.
- Local models download once, on first use, to `FASTEMBED_CACHE_PATH` (default `/data/models`, which is in the `runtime-data` volume). The default embedding model is about 2.2 GB and the reranker about 0.6 GB, so the first index build or reranked run is slow and needs that disk.
- Gemini embeddings send `taskType` (`RETRIEVAL_QUERY` or `RETRIEVAL_DOCUMENT`) in `embedContentConfig`, as the current API documents.
- A matrix holds at most four configs. Hosted embedding and reranker calls count against your provider quota.
- Text only, like Guide 9: retrieval is tested in typed conversations, not voice calls. Hindi and Kannada questions work with the multilingual default model; keyword search (`bm25`) uses an Indic-aware tokenizer but cannot match across languages.
