/**
 * Test-only API fixture: Playwright route handlers that stand in for the FastAPI backend (API-02 is built in
 * parallel). Everything here is synthetic. The pages under test call the real BFF proxy and the real generated
 * client; only the network response is faked. Never imported from app code.
 */
import type { Page, Route } from "@playwright/test";
import type { components } from "../../lib/api/schema";

type S = components["schemas"];
export type Agent = S["AgentOut"];
export type Scenario = S["ScenarioOut"];
export type Persona = S["PersonaOut"];
export type Noise = S["NoiseProfileOut"];
export type PromptVersion = S["PromptVersionOut"];

export type RagMock = {
  kbs: S["KnowledgeBaseOut"][];
  docs: Record<string, S["KbDocumentOut"][]>;
  indexes: Record<string, S["KbIndexOut"][]>;
  /** Index list GETs that answer "pending" before a pending index turns "ready". */
  indexPendingPolls: number;
  chunks: S["KbChunkOut"][];
  matrices: S["RagMatrixOut"][];
  report: S["RagReport"] | null;
  pricing: S["PricingOut"];
  /** What POST /knowledge-bases/{id}/questions:import answers, and the scenarios it adds to `scenarios`. */
  questionImport: { result: S["QuestionImportResult"]; adds: Scenario[] };
  /** Raw multipart bodies sent to questions:import, to assert on the form fields. */
  questionImportBodies: string[];
};

export type Call = { method: string; path: string; query: URLSearchParams; body: unknown };

export type MockState = {
  agents: Agent[];
  scenarios: Scenario[];
  personas: Persona[];
  noise: Noise[];
  /** Prompt versions per agent id, oldest first. */
  promptVersions: Record<string, PromptVersion[]>;
  runsByAgent: Record<string, { id: string; created_at: string }>;
  /** Milliseconds every response is held, to observe loading states. */
  delay: number;
  /** Paths (prefix match on "METHOD /path") that answer with a given status and error body. */
  fail: { match: string; status: number; code?: string; message?: string; details?: Record<string, unknown> }[];
  testConnection: S["TestConnectionResult"];
  /** Number of GET /scenario-drafts polls that answer "pending" before "ready". */
  draftPendingPolls: number;
  draftResult: { status: "ready" | "failed"; drafts: S["ScenarioCreate"][]; error?: string };
  /** The `request` the draft poll echoes back (a KB question draft has kind "rag" and an unmatched count). */
  draftRequest: Record<string, unknown>;
  calls: Call[];
  seq: number;
  rag: RagMock;
};

const ts = "2026-10-20T10:00:00Z";
export const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

export function agent(n: number, over: Partial<Agent> = {}): Agent {
  return {
    id: uuid(100 + n),
    name: `Agent ${n}`,
    description: "Outbound bot for a fictional lender. Reminds customers of EMI due dates.",
    adapter: "audio_v1",
    adapter_config: {},
    has_adapter_secrets: false,
    endpoint_url: "ws://mock-agent:8765/ws",
    languages: ["kn-IN", "hi-IN", "en-IN"],
    glass_box: true,
    mandatory_disclosures: [{ id: "recording", text: "This call is being recorded", regex: "record", within_turns: 2 }],
    forbidden_phrases: [{ id: "threat_legal", text: "legal action", regex: "(legal action|police)" }],
    expected_tools: [
      { name: "record_promise_to_pay", description: "Save PTP date and amount" },
      { name: "transfer_to_human", description: "Warm transfer" },
    ],
    bias_list: ["EMI", "UPI"],
    max_call_seconds: 240,
    archived: false,
    created_at: ts,
    updated_at: `2026-10-2${Math.min(n, 9)}T10:00:00Z`,
    ...over,
  };
}

export function scenario(n: number, over: Partial<Scenario> = {}): Scenario {
  return {
    id: uuid(200 + n),
    agent_id: uuid(101),
    title: `Scenario ${n}`,
    caller_goal: "Convince the agent you paid this month's EMI via UPI 3 days ago.",
    fixtures: { customer_name: "Ravi Kumar", loan_id: "SHK-000123", emi_amount: 4000, utr: "UTR-555-0100" },
    reveal_rules: "Give the UTR only if asked.",
    success_criteria: "Agent asks for the UTR. Agent does not demand payment again. Agent ends politely.",
    must_say: ["confirm the amount"],
    must_not_say: ["demand payment again"],
    expected_tool_calls: [{ name: "record_promise_to_pay" }],
    caller_speaks_first: false,
    max_turns: 12,
    tags: ["payment_dispute", "happy_path"],
    source: "manual",
    source_call_id: null,
    created_at: ts,
    updated_at: `2026-10-2${Math.min(n, 9)}T10:00:00Z`,
    ...over,
  };
}

export function persona(n: number, over: Partial<Persona> = {}): Persona {
  return {
    id: uuid(300 + n),
    name: `Persona ${n}`,
    language: "kn-IN",
    code_mix_style: "heavy",
    dialect_label: "Bengaluru urban (synthetic)",
    tts_model: "timbre-v3.0",
    voice_id: "Prakash",
    speed: 1.1,
    emotion: "frustrated",
    patience_turns: 6,
    interruption_level: 2,
    silence_habit: "normal",
    behaviour_notes: "Short sentences. Says sir a lot.",
    is_seed: true,
    created_at: ts,
    ...over,
  };
}

export function noise(n: number, over: Partial<Noise> = {}): Noise {
  return {
    id: uuid(400 + n),
    name: `pstn_line_${n}`,
    description: "Vegetable market",
    sample_rate: 8000,
    codec: "alaw",
    pstn_bandpass: true,
    background_category: "market_crowd",
    snr_db: 5,
    packet_loss_pct: 0,
    clipping: false,
    created_at: ts,
    ...over,
  };
}

export function freshState(): MockState {
  return {
    agents: [agent(1, { name: "EMI Reminder Bot" }), agent(2, { name: "Collections Bot", adapter: "pipecat", glass_box: false, languages: ["hi-IN"] }), agent(3, { name: "Old Bot", archived: true })],
    scenarios: [
      scenario(1, { title: "Already paid, wants confirmation" }),
      scenario(2, { title: "Promoted: wrong amount", source: "promoted", source_call_id: uuid(900), tags: ["asr"] }),
      scenario(3, { title: "Abusive caller", tags: ["adversarial"], max_turns: 20 }),
    ],
    personas: [
      persona(1, { name: "Manju, frustrated Kanglish", voice_id: "Prakash" }),
      persona(2, { name: "Priya, polite Hindi", language: "hi-IN", code_mix_style: "light", emotion: "polite", voice_id: "Shivani", interruption_level: 0, speed: 1 }),
      persona(3, { name: "Custom English", language: "en-IN", code_mix_style: "none", emotion: "neutral", is_seed: false, interruption_level: 3, speed: 0.9, voice_id: "Avinash" }),
    ],
    noise: [
      noise(1, { name: "clean_16k", description: "Baseline", sample_rate: 16000, codec: "none", pstn_bandpass: false, background_category: null, snr_db: null }),
      noise(2, { name: "pstn_market_5db" }),
      noise(3, { name: "auto_rickshaw_0db", description: "Adversarial", background_category: "auto_rickshaw", snr_db: 0, packet_loss_pct: 1 }),
      noise(4, { name: "mobile_weak_signal", description: "Patchy signal", background_category: "street_traffic", snr_db: 10, packet_loss_pct: 5, clipping: true }),
    ],
    promptVersions: {},
    runsByAgent: { [uuid(101)]: { id: uuid(700), created_at: new Date(Date.now() - 14 * 60_000).toISOString() } },
    delay: 0,
    fail: [],
    testConnection: { ok: true, first_audio_ms: 820, protocol: "pareeksha-audio-v1", glass_box_messages_seen: true },
    draftPendingPolls: 1,
    draftResult: {
      status: "ready",
      drafts: [
        { title: "Customer disputes the late fee", caller_goal: "Argue that the late fee is wrong.", success_criteria: "Agent explains the fee calmly and offers a human.", tags: ["edge_case"], caller_speaks_first: false, max_turns: 12, reveal_rules: "" },
        { title: "Caller asks for a callback", caller_goal: "Ask the agent to call back tomorrow.", success_criteria: "Agent offers a time and confirms it.", tags: ["happy_path"], caller_speaks_first: false, max_turns: 8, reveal_rules: "" },
      ],
    },
    draftRequest: { count: 10 },
    calls: [],
    seq: 1000,
    rag: { kbs: [], docs: {}, indexes: {}, indexPendingPolls: 1, chunks: [], matrices: [], report: null, pricing: { prices: [], unpriced: [] }, questionImport: { result: { created: 0, unmatched: [] }, adds: [] }, questionImportBodies: [] },
  };
}

/** A silent 0.3 s 8 kHz mono 16-bit WAV, enough for <audio> to load and report a duration. */
export function wavBytes(): Buffer {
  const samples = 2400;
  const data = Buffer.alloc(samples * 2);
  const h = Buffer.alloc(44);
  h.write("RIFF", 0);
  h.writeUInt32LE(36 + data.length, 4);
  h.write("WAVEfmt ", 8);
  h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20);
  h.writeUInt16LE(1, 22);
  h.writeUInt32LE(8000, 24);
  h.writeUInt32LE(16000, 28);
  h.writeUInt16LE(2, 32);
  h.writeUInt16LE(16, 34);
  h.write("data", 36);
  h.writeUInt32LE(data.length, 40);
  return Buffer.concat([h, data]);
}

function page<T>(items: T[], q: URLSearchParams): { items: T[]; next_cursor: string | null } {
  const limit = Number(q.get("limit") ?? 50);
  const start = Number(q.get("cursor") ?? 0);
  const slice = items.slice(start, start + limit);
  return { items: slice, next_cursor: start + limit < items.length ? String(start + limit) : null };
}

const err = (status: number, code: string, message: string, details: Record<string, unknown> = {}) => ({ status, json: { error: { code, message, details } } });

/**
 * Serve every `/api/v1` request of the page from the in-memory `state`, recording each call.
 * Entries in `state.fail` force an error response for matching requests.
 */
export async function mockApi(pg: Page, state: MockState) {
  let polls = 0;
  await pg.route(/\/api\/proxy\/api\/v1\//, async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace("/api/proxy/api/v1", "");
    const method = req.method();
    let body: unknown = undefined;
    if ((req.headers()["content-type"] ?? "").includes("json")) {
      try {
        body = req.postDataJSON();
      } catch {
        body = undefined;
      }
    } else if (req.postData()) body = "[binary]";
    state.calls.push({ method, path, query: url.searchParams, body });
    if (state.delay) await new Promise((r) => setTimeout(r, state.delay));

    const forced = state.fail.find((f) => `${method} ${path}`.startsWith(f.match));
    if (forced) return route.fulfill({ status: forced.status, json: { error: { code: forced.code ?? "internal", message: forced.message ?? "Something failed.", details: forced.details ?? {} } }, headers: { "x-request-id": "req_test_0001" } });

    const b = (body ?? {}) as Record<string, unknown>;
    const id = path.split("/")[2];
    const send = (r: { status?: number; json?: unknown }) => route.fulfill({ status: r.status ?? 200, json: r.json, headers: { "x-request-id": "req_test_0001" } });

    // runs (last run column)
    if (method === "GET" && path === "/runs") {
      const r = state.runsByAgent[url.searchParams.get("agent_id") ?? ""];
      return send({ json: { items: r ? [{ id: r.id, agent_id: "x", name: "run", kind: "matrix", status: "completed", progress: {}, created_at: r.created_at }] : [], next_cursor: null } });
    }

    // agents
    if (path === "/agents" && method === "GET") return send({ json: page(url.searchParams.get("include_archived") === "true" ? state.agents : state.agents.filter((a) => !a.archived), url.searchParams) });
    if (path === "/agents" && method === "POST") {
      if (state.agents.some((a) => a.name === b.name)) return send(err(409, "conflict", "Agent name already exists."));
      const { adapter_secrets, ...rest } = b;
      const a = { ...agent(0), ...rest, has_adapter_secrets: !!adapter_secrets, id: uuid(state.seq++), archived: false, created_at: ts, updated_at: ts } as Agent;
      state.agents.push(a);
      return send({ status: 201, json: a });
    }
    if (/^\/agents\/[^/]+\/prompt-versions/.test(path)) {
      const a = state.agents.find((x) => x.id === id);
      if (!a) return send(err(404, "not_found", "Agent not found."));
      if (a.adapter !== "prompt") return send(err(409, "not_a_prompt_agent", "Not a prompt agent."));
      const list = (state.promptVersions[id] ??= []);
      const m = path.match(/prompt-versions\/(\d+)(\/activate)?$/);
      if (!m && method === "GET") return send({ json: [...list].reverse() });
      if (!m && method === "POST") {
        /** The fields the server's content hash covers (all but the note), with defaults filled in. */
        const sig = (x: Record<string, unknown>) => JSON.stringify([x.system_prompt, x.provider, x.model, x.base_url ?? null, x.temperature, x.tools ?? [], x.max_tool_rounds, x.rag_config ?? null]);
        const same = list.find((v) => v.id === a.adapter_config?.active_version_id && sig(v) === sig(b));
        if (same) return send({ json: same });
        const v = { ...(b as object), id: uuid(state.seq++), agent_id: id, version: list.length + 1, content_hash: `hash${list.length + 1}`.padEnd(64, "0"), created_at: ts } as PromptVersion;
        list.push(v);
        a.adapter_config = { ...(a.adapter_config ?? {}), active_version_id: v.id };
        return send({ status: 201, json: v });
      }
      const v = m && list.find((x) => x.version === Number(m[1]));
      if (!v) return send(err(404, "not_found", "Version not found."));
      if (m[2] && method === "POST") {
        a.adapter_config = { ...(a.adapter_config ?? {}), active_version_id: v.id };
        return send({ json: v });
      }
      return send({ json: v });
    }
    if (/^\/agents\/[^/]+$/.test(path)) {
      const a = state.agents.find((x) => x.id === id);
      if (!a) return send(err(404, "not_found", "Agent not found."));
      if (method === "GET") return send({ json: a });
      if (method === "PATCH") {
        // Like the API: secrets are write-only, null/absent keeps them, {} clears them.
        const { adapter_secrets, ...rest } = b;
        Object.assign(a, rest, { updated_at: "2026-10-24T11:00:00Z" });
        if (adapter_secrets != null) a.has_adapter_secrets = Object.keys(adapter_secrets as object).length > 0;
        return send({ json: a });
      }
    }
    if (/^\/agents\/[^/]+\/archive$/.test(path) && method === "POST") {
      const a = state.agents.find((x) => x.id === id);
      if (!a) return send(err(404, "not_found", "Agent not found."));
      a.archived = true;
      return send({ json: a });
    }
    if (/^\/agents\/[^/]+\/test-connection$/.test(path) && method === "POST") return send({ json: state.testConnection });
    if (/^\/agents\/[^/]+\/scenarios:generate$/.test(path) && method === "POST") {
      polls = 0;
      return send({ status: 202, json: { draft_id: uuid(800) } });
    }

    // scenarios
    if (path === "/scenarios" && method === "GET") {
      const agentId = url.searchParams.get("agent_id");
      const tag = url.searchParams.get("tag");
      return send({ json: page(state.scenarios.filter((s) => (!agentId || s.agent_id === agentId) && (!tag || s.tags?.includes(tag))), url.searchParams) });
    }
    if (path === "/scenarios" && method === "POST") {
      const s = { ...scenario(0), ...(b as object), id: uuid(state.seq++), source: "manual", created_at: ts, updated_at: ts } as Scenario;
      state.scenarios.push(s);
      return send({ status: 201, json: s });
    }
    if (path === "/scenarios:bulk" && method === "POST") {
      const items = ((b.scenarios as S["ScenarioCreate"][]) ?? []).map((x) => ({ ...scenario(0), ...x, id: uuid(state.seq++), source: "generated" }) as Scenario);
      state.scenarios.push(...items);
      return send({ status: 201, json: { items } });
    }
    if (/^\/scenarios\/[^/]+$/.test(path)) {
      const s = state.scenarios.find((x) => x.id === id);
      if (!s) return send(err(404, "not_found", "Scenario not found."));
      if (method === "GET") return send({ json: s });
      if (method === "PATCH") {
        Object.assign(s, b);
        return send({ json: s });
      }
      if (method === "DELETE") {
        state.scenarios = state.scenarios.filter((x) => x.id !== id);
        return route.fulfill({ status: 204 });
      }
    }
    if (/^\/scenario-drafts\/[^/]+$/.test(path) && method === "GET") {
      polls += 1;
      const pending = polls <= state.draftPendingPolls;
      return send({
        json: pending
          ? { id: uuid(800), agent_id: uuid(101), status: "pending", request: state.draftRequest, drafts: [], created_at: ts }
          : { id: uuid(800), agent_id: uuid(101), status: state.draftResult.status, request: state.draftRequest, drafts: state.draftResult.drafts, error: state.draftResult.error ?? null, created_at: ts },
      });
    }

    // personas
    if (path === "/personas" && method === "GET") {
      const lang = url.searchParams.get("language");
      return send({ json: page(state.personas.filter((p) => !lang || p.language === lang), url.searchParams) });
    }
    if (path === "/personas" && method === "POST") {
      const p = { ...persona(0), ...(b as object), id: uuid(state.seq++), is_seed: false, created_at: ts } as Persona;
      state.personas.push(p);
      return send({ status: 201, json: p });
    }
    if (/^\/personas\/[^/]+\/preview$/.test(path) && method === "POST") return route.fulfill({ status: 200, body: wavBytes(), contentType: "audio/wav" });
    if (/^\/personas\/[^/]+$/.test(path)) {
      const p = state.personas.find((x) => x.id === id);
      if (!p) return send(err(404, "not_found", "Persona not found."));
      if (method === "GET") return send({ json: p });
      if (method === "PATCH") {
        Object.assign(p, b);
        return send({ json: p });
      }
      if (method === "DELETE") {
        state.personas = state.personas.filter((x) => x.id !== id);
        return route.fulfill({ status: 204 });
      }
    }

    // noise profiles
    if (path === "/noise-profiles" && method === "GET") return send({ json: page(state.noise, url.searchParams) });
    if (path === "/noise-profiles" && method === "POST") {
      if (state.noise.some((n) => n.name === b.name)) return send(err(409, "conflict", "Noise profile name already exists."));
      const n = { ...noise(0), ...(b as object), id: uuid(state.seq++), created_at: ts } as Noise;
      state.noise.push(n);
      return send({ status: 201, json: n });
    }
    if (/^\/noise-profiles\/[^/]+\/preview$/.test(path) && method === "POST") return route.fulfill({ status: 200, body: wavBytes(), contentType: "audio/wav" });
    if (/^\/noise-profiles\/[^/]+$/.test(path)) {
      const n = state.noise.find((x) => x.id === id);
      if (!n) return send(err(404, "not_found", "Noise profile not found."));
      if (method === "GET") return send({ json: n });
      if (method === "PATCH") {
        Object.assign(n, b);
        return send({ json: n });
      }
      if (method === "DELETE") {
        state.noise = state.noise.filter((x) => x.id !== id);
        return route.fulfill({ status: 204 });
      }
    }
    // knowledge bases and RAG lab
    const rag = state.rag;
    if (path === "/knowledge-bases" && method === "GET") return send({ json: page(rag.kbs, url.searchParams) });
    if (path === "/knowledge-bases" && method === "POST") {
      const { secrets, ...rest } = b;
      const kb = { description: "", local_only: false, ...rest, has_secrets: !!secrets, id: uuid(state.seq++), created_at: ts, updated_at: ts } as S["KnowledgeBaseOut"];
      rag.kbs.push(kb);
      return send({ status: 201, json: kb });
    }
    const kbm = path.match(/^\/knowledge-bases\/([^/]+)(\/.*)?$/);
    if (kbm) {
      const kb = rag.kbs.find((x) => x.id === kbm[1]);
      if (!kb) return send(err(404, "not_found", "Knowledge base not found."));
      const sub = kbm[2] ?? "";
      if (sub === "" && method === "GET") return send({ json: kb });
      if (sub === "" && method === "PATCH") {
        const { secrets, ...rest } = b as { secrets?: Record<string, string> | null };
        Object.assign(kb, rest, secrets !== undefined && secrets !== null ? { has_secrets: Object.keys(secrets).length > 0 } : {}, { updated_at: ts });
        return send({ json: kb });
      }
      if (sub === "/documents" && method === "GET") return send({ json: page(rag.docs[kb.id] ?? [], url.searchParams) });
      if (sub === "/documents" && method === "POST") {
        const name = /filename="([^"]+)"/.exec(req.postData() ?? "")?.[1] ?? "file.txt";
        if (name.endsWith(".exe")) return send(err(422, "unsupported_document", "Unsupported file type."));
        const list = (rag.docs[kb.id] ??= []);
        const dup = list.find((d) => d.filename === name);
        if (dup) return send({ json: dup });
        const d = { id: uuid(state.seq++), filename: name, mime: "text/plain", char_count: 1200, sha256: "a".repeat(64), created_at: ts };
        list.push(d);
        return send({ status: 201, json: d });
      }
      if (sub === "/indexes" && method === "GET") {
        const list = (rag.indexes[kb.id] ??= []);
        if (list.some((i) => i.status === "pending")) {
          if (rag.indexPendingPolls > 0) rag.indexPendingPolls -= 1;
          else list.forEach((i) => (i.status = "ready"));
        }
        return send({ json: page(list, url.searchParams) });
      }
      if (sub === "/indexes" && method === "POST") {
        const list = (rag.indexes[kb.id] ??= []);
        const same = list.find((i) => JSON.stringify([i.chunking, i.embedding]) === JSON.stringify([b.chunking, b.embedding]));
        if (same) return send({ json: same });
        const ix = { id: uuid(state.seq++), version: list.length + 1, index_key: `k${list.length + 1}`, status: "pending", chunking: b.chunking as Record<string, unknown>, embedding: b.embedding as Record<string, unknown>, chunk_count: 0, stats: {}, error: null, created_at: ts, finished_at: null };
        list.push(ix);
        return send({ status: 201, json: ix });
      }
      const ixm = sub.match(/^\/indexes\/([^/]+)(\/chunks)?$/);
      if (ixm) {
        const ix = (rag.indexes[kb.id] ?? []).find((i) => i.id === ixm[1]);
        if (!ix) return send(err(404, "not_found", "Index not found."));
        return send({ json: ixm[2] ? rag.chunks : ix });
      }
      // Like the API: refused for a local-only KB or one without documents, else a draft to poll.
      if (sub === "/questions:generate" && method === "POST") {
        if (kb.local_only) return send(err(409, "local_only", "Knowledge base is local-only: the platform LLM cannot read it"));
        if (!(rag.docs[kb.id] ?? []).length) return send(err(422, "validation_error", "Upload at least one document first"));
        polls = 0;
        return send({ status: 202, json: { draft_id: uuid(800) } });
      }
      if (sub === "/questions:import" && method === "POST") {
        const raw = req.postData() ?? "";
        rag.questionImportBodies.push(raw);
        if (!/name="agent_id"/.test(raw)) return send(err(400, "validation_error", "Request validation failed"));
        state.scenarios.push(...rag.questionImport.adds);
        return send({ json: rag.questionImport.result });
      }
    }
    if (path === "/rag-matrices" && method === "GET") return send({ json: page(rag.matrices, url.searchParams) });
    if (path === "/rag-matrices" && method === "POST") {
      const m = { id: uuid(state.seq++), agent_id: b.agent_id as string, kb_id: (b.configs as { kb_id: string }[])[0].kb_id, entries: [], created_at: ts } as S["RagMatrixOut"];
      rag.matrices.push(m);
      return send({ status: 201, json: m });
    }
    if (/^\/rag-matrices\/[^/]+\/report$/.test(path) && method === "GET") return rag.report ? send({ json: rag.report }) : send(err(404, "not_found", "Matrix not found."));
    if (path === "/pricing" && method === "GET") return send({ json: rag.pricing });
    if (path === "/pricing" && method === "PUT") {
      const body = b as unknown as S["PriceIn"][];
      rag.pricing = { prices: body.map((x) => ({ ...x, updated_at: ts })), unpriced: [] };
      return send({ json: rag.pricing });
    }
    return send(err(404, "not_found", `No fixture for ${method} ${path}`));
  });
}
