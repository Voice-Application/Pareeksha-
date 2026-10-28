/** Test-only API fixture for the runs / call detail / ops pages (synthetic data; the real-stack run is in proof/FE-03). */
import type { Page, Route } from "@playwright/test";
import { agent, persona, noise, scenario, uuid } from "./mock-api";

/** 14 s of silence, 8 kHz mono 16-bit, so seeking to 9 s works. */
function longWav(): Buffer {
  const data = Buffer.alloc(8000 * 2 * 14);
  const h = Buffer.alloc(44);
  h.write("RIFF", 0); h.writeUInt32LE(36 + data.length, 4); h.write("WAVEfmt ", 8); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22);
  h.writeUInt32LE(8000, 24); h.writeUInt32LE(16000, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write("data", 36); h.writeUInt32LE(data.length, 40);
  return Buffer.concat([h, data]);
}

const ts = "2026-10-24T10:00:00Z";
export const RUN_ID = uuid(900);
export const CALL_ID = uuid(901);

export const items = [
  { id: uuid(910), scenario: "Already paid", persona: "Manju", noise_profile: "clean_16k", status: "evaluated", call_id: CALL_ID, overall_score: 48.75, passed: false, critical_failure: true },
  { id: uuid(911), scenario: "Already paid", persona: "Sunita", noise_profile: "clean_16k", status: "evaluated", call_id: uuid(902), overall_score: 92.5, passed: true, critical_failure: false },
  { id: uuid(912), scenario: "Promise to pay", persona: "Manju", noise_profile: "clean_16k", status: "evaluated", call_id: uuid(903), overall_score: 71, passed: false, critical_failure: false },
  { id: uuid(913), scenario: "Promise to pay", persona: "Sunita", noise_profile: "clean_16k", status: "in_progress", call_id: null, overall_score: null, passed: null, critical_failure: null },
];

export const run = (over: Record<string, unknown> = {}) => ({
  id: RUN_ID,
  agent_id: agent(1).id,
  name: "Prompt v3 baseline",
  kind: "matrix",
  status: "completed",
  progress: { total: 4, queued: 0, in_progress: 0, evaluated: 4, error: 0 },
  summary: { pass_rate: 0.5, critical_failures: 1, needs_review: 1, score_mean: 70.9, latency_p50_ms: 1100, latency_p95_ms: 2300, barge_in_honoured_rate: 0.5, top_failure_types: [["wrong_fact", 2]], score_distribution: [0, 0, 0, 0, 1, 0, 0, 1, 0, 1] },
  created_at: ts,
  finished_at: ts,
  ...over,
});

const turns = [
  { idx: 0, speaker: "agent", text: "Namaskara, this call is recorded.", start_ms: 800, end_ms: 3800, is_barge_in: false },
  { idx: 1, speaker: "caller", text: "I paid four thousand.", ground_truth_text: "I paid four thousand.", agent_heard_text: "I paid forty thousand.", start_ms: 4400, end_ms: 6400, is_barge_in: false },
  { idx: 2, speaker: "agent", text: "Confirming forty thousand.", start_ms: 9000, end_ms: 11000, is_barge_in: false },
];

export const callDetail = (over: Record<string, unknown> = {}) => ({
  id: CALL_ID,
  source: "simulation",
  status: "completed",
  agent_id: agent(1).id,
  run_id: RUN_ID,
  language: "kn-IN",
  duration_ms: 12000,
  recordings: { mixed: "a/mixed.wav", caller: "a/caller.wav", agent: "a/agent.wav" },
  turns,
  tool_calls: [{ seq: 0, name: "record_promise_to_pay", arguments: { amount: 40000 }, at_ms: 10000, turn_idx: 2 }],
  metrics: { barge_in_attempts: 0, barge_in_honoured: 0, silence_gaps_over_2s: 0, turn_count: 3, repeated_utterances: 0, latency_is_approximate: false, response_latency_p50_ms: 2600, response_latency_p95_ms: 2600, first_greeting_ms: 800, agent_talk_ratio: 0.6 },
  checks: [{ check_type: "amount_confirmed", check_key: "emi_amount", must_pass: true, passed: false, evidence_turns: [2], detail: "Agent confirmed 40000, expected 4000" }],
  evaluation: {
    id: uuid(950),
    rubric_version: "rubric-2026-10-v1",
    judge_model: "deepseek-v4-pro",
    prompt_hash: "sha256:x",
    status: "ok",
    overall_score: 48.75,
    passed: false,
    critical_failure: true,
    needs_human_review: true,
    review_reasons: ["critical_failure"],
    failure_types: ["wrong_fact"],
    summary: "Agent confirmed 40,000 when the caller said 4,000. The caller objected and the agent recorded it anyway.",
    confidence: "medium",
    dimensions: {
      task_completion: { score: 1, evidence_turns: [2], reason: "Recorded the wrong amount." },
      policy_compliance: { score: 3, evidence_turns: [0], reason: "Disclosure given." },
      factual_accuracy: { score: 0, evidence_turns: [1, 2], reason: "Confirmed 40,000 instead of 4,000." },
      language_handling: { score: 4, evidence_turns: [], reason: "Fine." },
      conversation_flow: { score: 3, evidence_turns: [], reason: "Fine." },
      empathy_tone: { score: 3, evidence_turns: [], reason: "Fine." },
      escalation: { score: 4, evidence_turns: [], reason: "None needed." },
    },
  },
  ...over,
});

export type OpsState = { dlq: Record<string, unknown>[]; keys: Record<string, unknown>[]; fail: Record<string, number>; created: unknown[]; sse: string; /** "METHOD /path" -> JSON answered as 200 (or [status, json]) before the built-in routes. */ extra: Record<string, unknown>; revealed: Record<string, unknown>[] };

export const opsState = (): OpsState => ({
  dlq: [{ id: uuid(960), event_id: uuid(961), original_topic: "pareeksha.call.completed.v1", consumer_group: "evaluator", error: "JudgeSchemaError: invalid JSON from judge", attempts: 3, status: "open", failed_at: ts, envelope: { type: "call.completed", payload: { call_id: CALL_ID } } }],
  keys: [{ id: uuid(970), name: "demo", prefix: "pk_live_AaJPXAkX", scopes: ["admin"], created_at: ts, last_used_at: null, revoked_at: null }],
  fail: {},
  created: [],
  sse: "",
  extra: {},
  revealed: [],
});

/** Routes every endpoint the new pages call. `state.fail["GET /path"] = status` forces an error. */
export async function mockFe(pg: Page, st: OpsState, opts: { runStatus?: string; callOver?: Record<string, unknown>; runItems?: typeof items } = {}) {
  await pg.route(/\/api\/proxy\/api\/v1\//, async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace("/api/proxy/api/v1", "");
    const method = req.method();
    const key = `${method} ${path}`;
    const send = (json: unknown, status = 200) => route.fulfill({ status, json, headers: { "x-request-id": "req_test_0001" } });
    const forced = Object.entries(st.fail).find(([k]) => key.startsWith(k));
    if (forced) return send({ error: { code: forced[1] === 501 ? "not_implemented" : "internal", message: "Forced failure.", details: { owner: "TEST-01" } } }, forced[1]);
    const page = (list: unknown[]) => ({ items: list, next_cursor: null });
    if (key in st.extra) { const v = st.extra[key]; return Array.isArray(v) && typeof v[0] === "number" && v.length === 2 ? send(v[1], v[0] as number) : send(v); }

    if (path === "/agents") return send(page([agent(1)]));
    if (/^\/agents\/[^/]+$/.test(path)) return send(agent(1));
    if (path === "/scenarios") return send(page([scenario(1), scenario(2)]));
    if (path === "/personas") return send(page([persona(1), persona(2)]));
    if (path === "/noise-profiles") return send(page([noise(1), noise(2)]));
    if (path === "/usage") return send({ items: [], credits_used: 12.5, budget_credits: 500, remaining_budget: 487.5 });
    if (path === "/metrics/summary") return send({ consumer_lag: { evaluator: 0, planner: 2 }, outbox_backlog: 0, dlq_open: st.dlq.filter((d) => d.status === "open").length, credits_used: 12.5 });
    if (path === "/health") return send({ db: "ok", kafka: "ok" });
    if (path === "/runs:estimate") return send({ item_count: 4, estimate: { tts_seconds: 120, stt_seconds: 240, judge_calls: 4, caller_llm_calls: 20, est_cost: 31.5 }, remaining_budget: 487.5, over_budget: false });
    if (path === "/runs" && method === "POST") return send({ id: RUN_ID, status: "queued", item_count: 4, estimate: { tts_seconds: 120, stt_seconds: 240, judge_calls: 4, caller_llm_calls: 20, est_cost: 31.5 } }, 201);
    if (path === "/runs") return send(page([run({ status: opts.runStatus ?? "completed" }), run({ id: uuid(901 + 100), name: "Nightly regression", kind: "regression", summary: { suite_passed: false } }), run({ id: uuid(902 + 100), name: "Live one", status: "running", summary: {}, progress: { total: 12, queued: 5, in_progress: 0, evaluated: 7, error: 0 } })]));
    if (path === `/runs/${RUN_ID}/items`) return send(page(opts.runItems ?? items));
    if (path === `/runs/${RUN_ID}/events`) return route.fulfill({ status: 200, headers: { "content-type": "text/event-stream" }, body: st.sse });
    if (path === `/runs/${RUN_ID}`) return send(run(opts.runStatus === "running" ? { status: "running", progress: { total: 4, queued: 1, in_progress: 1, evaluated: 2, error: 0 }, summary: {} } : {}));
    if (path === "/calls" && method === "GET") return send(page([{ id: CALL_ID, source: "simulation", status: "completed", run_id: RUN_ID, language: "kn-IN", duration_ms: 12000, overall_score: 48.75, passed: false, critical_failure: true, needs_human_review: true, review_reasons: ["critical_failure"], failure_types: ["wrong_fact"], human_reviewed: false }]));
    if (path === `/calls/${CALL_ID}/review` && method === "POST") return send({ id: uuid(980), evaluation_id: uuid(950), reviewer: "x", passed: false, critical_failure: true }, 201);
    if (path === `/calls/${CALL_ID}`) return send(callDetail(opts.callOver));
    if (/\/calls\/[^/]+\/audio\//.test(path)) {
      // Range support is what makes <audio> seekable (same as the real endpoint).
      const wav = longWav();
      const m = /bytes=(\d+)-(\d*)/.exec(req.headers()["range"] ?? "");
      if (!m) return route.fulfill({ status: 200, headers: { "content-type": "audio/wav", "accept-ranges": "bytes", "content-length": String(wav.length) }, body: wav });
      const a = Number(m[1]);
      const b = m[2] ? Math.min(Number(m[2]), wav.length - 1) : wav.length - 1;
      return route.fulfill({ status: 206, headers: { "content-type": "audio/wav", "accept-ranges": "bytes", "content-range": `bytes ${a}-${b}/${wav.length}`, "content-length": String(b - a + 1) }, body: wav.subarray(a, b + 1) });
    }
    if (path === "/dlq" && method === "GET") return send(page(st.dlq.filter((d) => !url.searchParams.get("status") || d.status === url.searchParams.get("status"))));
    if (/^\/dlq\/[^/]+\/(replay|discard)$/.test(path)) {
      const d = st.dlq.find((x) => x.id === path.split("/")[2]);
      if (d) d.status = path.endsWith("replay") ? "replayed" : "discarded";
      return send(d);
    }
    if (path === "/api-keys" && method === "GET") return send(page(st.keys));
    if (path === "/api-keys" && method === "POST") {
      const b = req.postDataJSON() as { name: string; scopes: string[] };
      const k = { id: uuid(990 + st.keys.length), name: b.name, prefix: "pk_live_Zz9Yy8Xx", scopes: b.scopes, created_at: ts, last_used_at: null, revoked_at: null };
      st.keys.push(k);
      st.created.push(b);
      return send({ ...k, key: "pk_live_Zz9Yy8Xx_SECRET_SHOWN_ONCE" }, 201);
    }
    if (/^\/api-keys\/[^/]+$/.test(path) && method === "DELETE") {
      const k = st.keys.find((x) => x.id === path.split("/")[2]);
      if (k) k.revoked_at = ts;
      return route.fulfill({ status: 204 });
    }
    return send({ error: { code: "not_found", message: `unmocked ${key}`, details: {} } }, 404);
  });
}
