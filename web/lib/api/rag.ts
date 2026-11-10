import { api } from "./client";
import { ApiError, call } from "./call";
import type { components } from "./schema";

type S = components["schemas"];
export type KnowledgeBase = S["KnowledgeBaseOut"];
export type KbDocument = S["KbDocumentOut"];
export type KbIndex = S["KbIndexOut"];
export type KbChunk = S["KbChunkOut"];
export type RagConfig = S["RagConfig"];
export type RagMatrix = S["RagMatrixOut"];
export type RagMatrixCreate = S["RagMatrixCreate"];
export type RagReport = S["RagReport"];
export type ReportRow = S["ReportRow"];
export type PriceIn = S["PriceIn"];
export type Pricing = S["PricingOut"];
export type ChunkingConfig = S["ChunkingConfig"];
export type EmbeddingConfig = S["EmbeddingConfig"];

/** Response types carry the span as number[]; requests want a pair. */
const toSpan = (x: readonly number[] | null | undefined): [number, number] | null => (x && x.length === 2 ? [x[0], x[1]] : null);

type ExpectationRead = { source_document_id?: string | null; source_span?: number[] | null; reference_answer: string; answerable: boolean };
export type ScenarioRead = Omit<S["ScenarioOut"], "rag_expectation"> & { rag_expectation?: ExpectationRead | null };
export const toExpectation = (e: ExpectationRead | null | undefined): S["RagExpectation"] | null | undefined => (e ? { ...e, source_span: toSpan(e.source_span) } : e);

export const listKnowledgeBases = () => call(api.GET("/api/v1/knowledge-bases", { params: { query: { limit: 200 } } }));
export const getKnowledgeBase = (kb_id: string) => call(api.GET("/api/v1/knowledge-bases/{kb_id}", { params: { path: { kb_id } } }));
export const createKnowledgeBase = (body: S["KnowledgeBaseCreate"]) => call(api.POST("/api/v1/knowledge-bases", { body }));
/** PATCH a knowledge base; `secrets` replaces the stored provider keys (`{}` clears them). Keys are write-only. */
export const updateKnowledgeBase = (kb_id: string, body: S["KnowledgeBaseUpdate"]) => call(api.PATCH("/api/v1/knowledge-bases/{kb_id}", { params: { path: { kb_id } }, body }));
export const listDocuments = (kb_id: string) => call(api.GET("/api/v1/knowledge-bases/{kb_id}/documents", { params: { path: { kb_id }, query: { limit: 200 } } }));
export const listIndexes = (kb_id: string) => call(api.GET("/api/v1/knowledge-bases/{kb_id}/indexes", { params: { path: { kb_id }, query: { limit: 200 } } }));
export const getIndex = (kb_id: string, index_id: string) => call(api.GET("/api/v1/knowledge-bases/{kb_id}/indexes/{index_id}", { params: { path: { kb_id, index_id } } }));
export const listChunks = (kb_id: string, index_id: string, offset: number, limit: number, document_id?: string) =>
  call(api.GET("/api/v1/knowledge-bases/{kb_id}/indexes/{index_id}/chunks", { params: { path: { kb_id, index_id }, query: { offset, limit, document_id: document_id || null } } }));

/** 201 is a new index version; 200 means an identical index already existed and is returned unchanged. */
export async function buildIndex(kb_id: string, body: S["KbIndexCreate"]): Promise<{ index: KbIndex; created: boolean }> {
  const req = api.POST("/api/v1/knowledge-bases/{kb_id}/indexes", { params: { path: { kb_id } }, body });
  const index = await call(req);
  const { response } = await req;
  return { index, created: response.status === 201 };
}

/** POST a multipart form through the BFF proxy (openapi-fetch does not build multipart bodies); throws ApiError on any non-2xx or network failure. */
async function postForm<T>(path: string, fd: FormData): Promise<{ body: T; status: number }> {
  let res: Response;
  try {
    res = await fetch(`/api/proxy/api/v1${path}`, { method: "POST", body: fd });
  } catch {
    throw new ApiError(0, "network", "The API did not respond.");
  }
  const body = (await res.json().catch(() => null)) as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } & T;
  if (!res.ok) throw new ApiError(res.status, body?.error?.code ?? "unknown", body?.error?.message ?? res.statusText, body?.error?.details ?? {}, res.headers.get("x-request-id") ?? undefined);
  return { body, status: res.status };
}

/** Multipart upload through the BFF proxy. 201 = stored, 200 = the same file was already in the KB. */
export async function uploadDocument(kb_id: string, file: File): Promise<{ doc: KbDocument; created: boolean }> {
  const fd = new FormData();
  fd.append("file", file);
  const { body, status } = await postForm<KbDocument>(`/knowledge-bases/${kb_id}/documents`, fd);
  return { doc: body, created: status === 201 };
}

export type QuestionImportResult = S["QuestionImportResult"];
export type QuestionUnmatched = S["QuestionUnmatched"];
export type ScenarioDraft = S["ScenarioDraftOut"];
/** A generated question as the draft endpoint returns it (the span comes back as number[]). */
export type QuestionDraft = Omit<S["ScenarioCreate"], "rag_expectation"> & { rag_expectation?: ExpectationRead | null };

/** The CSV header `questions:import` requires, in order (backend/pareeksha/rag/questions.py CSV_COLUMNS). */
export const QUESTION_CSV_COLUMNS = ["question", "expected_answer", "source_document", "source_quote"] as const;

/** Starts LLM generation; the answer is a draft id to poll with getScenarioDraft. Nothing is saved until saveQuestionDrafts. */
export const generateQuestions = (kb_id: string, body: S["QuestionGenerateRequest"]) => call(api.POST("/api/v1/knowledge-bases/{kb_id}/questions:generate", { params: { path: { kb_id } }, body }));
export const getScenarioDraft = (draft_id: string) => call(api.GET("/api/v1/scenario-drafts/{draft_id}", { params: { path: { draft_id } } }));
/** Save reviewed question drafts as scenarios (source "generated"). */
export const saveQuestionDrafts = (drafts: QuestionDraft[]) => call(api.POST("/api/v1/scenarios:bulk", { body: { scenarios: drafts.map((d) => ({ ...d, rag_expectation: toExpectation(d.rag_expectation) })), source: "generated" } }));

/** Upload a question CSV; every matched row becomes a scenario for `agent_id`, the others come back as unmatched rows. */
export async function importQuestions(kb_id: string, agent_id: string, file: File): Promise<QuestionImportResult> {
  const fd = new FormData();
  fd.append("agent_id", agent_id);
  fd.append("file", file);
  return (await postForm<QuestionImportResult>(`/knowledge-bases/${kb_id}/questions:import`, fd)).body;
}

/** Every scenario tagged `rag` in the project, following the cursor (the API has no knowledge-base filter, so callers match on the source document). */
export async function listQuestionScenarios(): Promise<ScenarioRead[]> {
  const out: ScenarioRead[] = [];
  let cursor: string | null = null;
  for (let pages = 0; pages < 25; pages++) {
    const p = (await call(api.GET("/api/v1/scenarios", { params: { query: { tag: "rag", limit: 200, cursor } } }))) as { items?: ScenarioRead[]; next_cursor?: string | null };
    out.push(...(p.items ?? []));
    cursor = p.next_cursor ?? null;
    if (!cursor) break;
  }
  return out;
}

/** Plain-words reason for an unmatched CSV row. */
export const UNMATCHED_REASONS: Record<QuestionUnmatched["reason"], string> = {
  document_not_found: "No document in this knowledge base has the file name given in source_document.",
  quote_not_found: "The source_quote text is not in that document. Copy it from the document exactly; case and spacing may differ.",
  empty_question: "The question is empty.",
};

/** Question generation and import errors: the API's own message, plus what to do instead when the knowledge base is local only. */
export function questionErrorMessage(e: unknown): string {
  if (!(e instanceof ApiError)) return "The request failed.";
  if (e.code === "local_only") return `${e.userMessage().replace(/\.?$/, ".")} Import your own questions from a CSV instead, or turn off Local only on the knowledge base.`;
  if (e.code === "file_too_large") return FRIENDLY.file_too_large;
  return e.userMessage();
}

export const listMatrices = () => call(api.GET("/api/v1/rag-matrices", { params: { query: { limit: 200 } } }));
export const getReport = (id: string, monthly_conversations: number) => call(api.GET("/api/v1/rag-matrices/{id}/report", { params: { path: { id }, query: { monthly_conversations } } }));
export const createMatrix = (body: RagMatrixCreate) => call(api.POST("/api/v1/rag-matrices", { body }));
export const getPricing = () => call(api.GET("/api/v1/pricing"));
export const putPricing = (body: PriceIn[]) => call(api.PUT("/api/v1/pricing", { body }));

export type MissingIndex = { label: string; chunking: ChunkingConfig; embedding: EmbeddingConfig };

/** The indexes a 409 rag_index_missing asks for, in the shape the build endpoint takes. */
export function missingIndexes(e: unknown): MissingIndex[] {
  if (!(e instanceof ApiError) || e.code !== "rag_index_missing") return [];
  const m = (e.details as { missing?: MissingIndex[] }).missing;
  return Array.isArray(m) ? m : [];
}

const FRIENDLY: Record<string, string> = {
  local_only: "This knowledge base is local only. Use the local embedding model and reranker, and a model running on this deployment, or turn off Local only on the knowledge base.",
  rag_index_missing: "No ready index matches this setup. Build the index first.",
  full_context_too_large: "The whole knowledge base is larger than the full-context limit, so it cannot be sent to the model as one block. Use retrieval instead, or raise the limit.",
  kb_limit_reached: "This knowledge base is full: at most 200 documents and 2,000,000 characters. Delete a document to add more.",
  file_too_large: "That file is over 10 MB. Split it or export a smaller one.",
  unsupported_document: "Pareeksha cannot read this file type. Use txt, md, html, csv, json, pdf or docx.",
  extraction_failed: "The text could not be extracted from this file. It may be encrypted, scanned images only, or damaged.",
  base_url_not_allowed: "That endpoint is not allowed: it must be https on a public address. A private server (for example Ollama on your network) needs OLLAMA_BASE_URL or AGENT_LLM_ALLOW_PRIVATE_URLS set on the server.",
};

/** Plain sentence for the RAG error codes; other errors keep the API's own message. */
export function ragErrorMessage(e: unknown): string {
  if (e instanceof ApiError) return FRIENDLY[e.code] ?? e.userMessage();
  return "The request failed.";
}

export const DEFAULT_RAG: Omit<RagConfig, "kb_id"> = {
  mode: "retrieval",
  chunking: { strategy: "recursive", size: 800, overlap: 100, window: 2 },
  embedding: { provider: "local", model: "intfloat/multilingual-e5-large" },
  method: "hybrid",
  top_k: 5,
  candidate_k: 20,
  rrf_k: 60,
  mmr_lambda: 0.5,
  reranker_provider: "local",
  reranker_model: "BAAI/bge-reranker-v2-m3-int8",
  query_transform: "none",
  small_to_big: false,
  context_char_limit: 400000,
  label: "",
};

export const METHODS: { value: RagConfig["method"]; label: string }[] = [
  { value: "bm25", label: "BM25 (keywords)" },
  { value: "dense", label: "Dense (embeddings)" },
  { value: "hybrid", label: "Hybrid (BM25 + dense)" },
  { value: "hybrid_rerank", label: "Hybrid + reranker" },
  { value: "mmr", label: "MMR (diverse)" },
];

export const EMBEDDING_PROVIDERS: EmbeddingConfig["provider"][] = ["local", "gemini", "openai", "openai_compatible", "azure_openai", "cohere", "voyage", "jina", "mistral", "bedrock", "ollama"];

/** Providers whose endpoint you type in: required for these, optional for Ollama (empty = the server's OLLAMA_BASE_URL). */
const ENDPOINT_REQUIRED: EmbeddingConfig["provider"][] = ["openai_compatible", "azure_openai", "bedrock"];
const ENDPOINT_EXAMPLE: Partial<Record<EmbeddingConfig["provider"], string>> = {
  ollama: "http://ollama:11434/v1",
  openai_compatible: "https://embeddings.example.com/v1",
  azure_openai: "https://<resource>.openai.azure.com/openai/deployments/<deployment>",
  bedrock: "https://bedrock-runtime.us-east-1.amazonaws.com",
};

/** Whether the embedding endpoint field shows for `provider`, whether it must be filled, and its placeholder. */
export function embeddingEndpoint(provider: EmbeddingConfig["provider"]): { show: boolean; required: boolean; placeholder: string } {
  const placeholder = ENDPOINT_EXAMPLE[provider] ?? "";
  return { show: provider === "ollama" || ENDPOINT_REQUIRED.includes(provider), required: ENDPOINT_REQUIRED.includes(provider), placeholder };
}

/** Help text under the endpoint field. */
export function embeddingEndpointHelp(provider: EmbeddingConfig["provider"]): string {
  if (provider === "ollama") return "Leave empty for the Ollama server this deployment is set up with (OLLAMA_BASE_URL, by default the ollama container).";
  if (provider === "azure_openai") return "Your resource's deployment URL. The API key goes in Provider keys on the knowledge base page.";
  if (provider === "bedrock") return "The bedrock-runtime URL of your region. The Bedrock API key goes in Provider keys.";
  return "The base URL; Pareeksha calls <url>/embeddings. The API key goes in Provider keys.";
}

/** Does this ready index have the chunking and embedding a config asks for? Matches the fields that decide the index key. */
export function indexMatches(ix: KbIndex, c: Pick<RagConfig, "chunking" | "embedding">): boolean {
  const ch = ix.chunking as Partial<ChunkingConfig>;
  const em = ix.embedding as Partial<EmbeddingConfig>;
  const wantCh = c.chunking ?? DEFAULT_RAG.chunking!;
  const wantEm = c.embedding ?? DEFAULT_RAG.embedding!;
  return ch.strategy === wantCh.strategy && ch.size === wantCh.size && ch.overlap === wantCh.overlap && em.provider === wantEm.provider && em.model === wantEm.model;
}

export const pct = (x: number | null | undefined, digits = 0) => (x == null ? "n/a" : `${(x * 100).toFixed(digits)}%`);
/** "71% (58–81%)" */
export const pctCi = (x: number | null | undefined, ci: readonly number[] | null | undefined) =>
  x == null ? "n/a" : ci && ci.length === 2 ? `${pct(x)} (${(ci[0] * 100).toFixed(0)}–${(ci[1] * 100).toFixed(0)}%)` : pct(x);
export const ms = (x: number | null | undefined) => (x == null ? "n/a" : `${Math.round(x).toLocaleString("en-IN")} ms`);
export const inr = (x: number | null | undefined, digits = 2) => (x == null ? "unpriced" : `₹${x.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`);
