import { test, expect, type Page } from "@playwright/test";
import { agent, freshState, mockApi, scenario, uuid, type MockState } from "./support/mock-api";

async function open(page: Page, path: string, mutate?: (s: MockState) => void) {
  const state = freshState();
  mutate?.(state);
  await mockApi(page, state);
  await page.goto(path);
  return state;
}

const kbId = uuid(500);
const pid = uuid(150);
const ts = "2026-10-20T10:00:00Z";
const chunking = { strategy: "recursive", size: 800, overlap: 100, window: 2 };
const embedding = { provider: "local", model: "intfloat/multilingual-e5-large" };
const kb = { id: kbId, name: "Loan policy", description: "FAQ", local_only: false, has_secrets: false, created_at: ts, updated_at: ts };
const readyIndex = { id: uuid(510), version: 1, index_key: "k1", status: "ready", chunking, embedding, chunk_count: 42, stats: {}, error: null, created_at: ts, finished_at: ts };

const withKb = (indexes = [readyIndex]) => (s: MockState) => {
  s.rag.kbs.push(kb);
  s.rag.indexes[kbId] = indexes.map((i) => ({ ...i }));
};
const promptAgent = (s: MockState) => void s.agents.push(agent(50, { adapter: "prompt", name: "Prompt Bot" }));

test.describe("RAG lab", () => {
  test("create a knowledge base, upload (with dedupe) and build an index that goes pending to ready", async ({ page }) => {
    const s = await open(page, "/knowledge-bases");
    await page.getByLabel("Name").fill("Loan policy");
    await page.getByRole("switch", { name: "Local only" }).click();
    await expect(page.getByText("Documents never leave this deployment")).toBeVisible();
    await page.getByRole("button", { name: "Create knowledge base" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Loan policy" })).toBeVisible();
    expect(s.calls.find((c) => c.method === "POST" && c.path === "/knowledge-bases")?.body).toMatchObject({ name: "Loan policy", local_only: true });

    const file = { name: "faq.txt", mimeType: "text/plain", buffer: Buffer.from("Late fee is 2 percent.") };
    await page.getByLabel("Documents to upload").setInputFiles(file);
    await expect(page.getByText("Uploaded, 1,200 characters.")).toBeVisible();
    await page.getByLabel("Documents to upload").setInputFiles(file);
    await expect(page.getByText("Already uploaded.")).toBeVisible();
    await page.getByLabel("Documents to upload").setInputFiles({ name: "x.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ") });
    await expect(page.getByRole("alert").filter({ hasText: "cannot read this file type" })).toBeVisible();

    await page.getByRole("button", { name: "Build index" }).click();
    const idx = page.getByRole("table", { name: "Indexes" });
    await expect(idx.getByText("pending")).toBeVisible();
    await expect(idx.getByText("ready")).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Build index" }).click();
    await expect(page.getByText("Using existing index v1.")).toBeVisible();
  });

  test("version editor saves RAG settings and offers to build a missing index", async ({ page }) => {
    const s = await open(page, `/agents/${pid}`, (st) => {
      promptAgent(st);
      withKb()(st);
    });
    await page.getByLabel("Model").fill("gpt-4o-mini");
    await page.getByLabel("System prompt").fill("Answer from the policy.\n{{context}}");
    await page.getByRole("switch", { name: "Retrieve from a knowledge base" }).click();
    await expect(page.getByText("{{context}}").first()).toBeVisible();
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByText("Choose the knowledge base this prompt retrieves from.")).toBeVisible();
    await expect(page.getByLabel("Knowledge base", { exact: true })).toHaveAttribute("aria-describedby", /error/);
    await page.getByLabel("Knowledge base", { exact: true }).selectOption(kbId);
    await expect(page.getByText("is ready for this chunking and embedding")).toBeVisible();
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved v1" })).toBeVisible();
    const post = s.calls.find((c) => c.method === "POST" && c.path.endsWith("/prompt-versions"));
    expect(post?.body).toMatchObject({ rag_config: { kb_id: kbId, mode: "retrieval", method: "hybrid", top_k: 5 } });

    await page.getByLabel("Size (chars)").fill("500");
    await expect(page.getByText("No ready index matches")).toBeVisible();
    await page.getByRole("button", { name: "Build it" }).click();
    await expect.poll(() => s.calls.some((c) => c.method === "POST" && c.path === `/knowledge-bases/${kbId}/indexes`)).toBe(true);
    expect(s.calls.find((c) => c.path === `/knowledge-bases/${kbId}/indexes` && c.method === "POST")?.body).toMatchObject({ chunking: { size: 500 } });
  });

  test("new matrix shows rag_index_missing with Build buttons", async ({ page }) => {
    const s = await open(page, "/rag-lab/new", (st) => {
      promptAgent(st);
      withKb([])(st);
      st.scenarios.push(scenario(9, { title: "Refund policy question", tags: ["rag"] }));
      st.fail.push({ match: "POST /rag-matrices", status: 409, code: "rag_index_missing", message: "No ready index.", details: { missing: [{ label: "Config 1", chunking, embedding }] } });
    });
    await page.getByLabel("Prompt agent").selectOption({ label: "Prompt Bot" });
    await page.getByLabel("Knowledge base", { exact: true }).selectOption(kbId);
    await expect(page.getByRole("region", { name: "Config 1" })).toBeVisible();
    await page.getByRole("button", { name: "Duplicate config 1" }).click();
    await expect(page.getByRole("region", { name: "Config 2" })).toBeVisible();
    await page.getByRole("button", { name: "Remove config 2" }).click();
    await page.getByRole("checkbox", { name: "Refund policy question" }).check();
    await page.getByRole("checkbox", { name: "Manju, frustrated Kanglish" }).check();
    await page.getByRole("checkbox", { name: "clean_16k" }).check();
    await page.getByRole("button", { name: "Run matrix" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "No ready index matches this setup" })).toBeVisible();
    await page.getByRole("button", { name: "Build index for Config 1" }).click();
    await expect(page.getByText("Building index v1.")).toBeVisible();
    const build = s.calls.find((c) => c.method === "POST" && c.path === `/knowledge-bases/${kbId}/indexes`);
    expect(build?.body).toMatchObject({ chunking: { strategy: "recursive", size: 800 }, embedding: { provider: "local" } });
  });

  test("report shows CIs, an n/a row with its reason and the recommendation reason", async ({ page }) => {
    const mid = uuid(600);
    const noRagRun = uuid(601);
    const ragRun = uuid(602);
    const base = { n_calls: 12, n_questions_with_truth: 12 };
    await open(page, `/rag-lab/${mid}`, (st) => {
      st.rag.report = {
        matrix_id: mid,
        monthly_conversations: 10000,
        recommendation: { label: "Hybrid 800", reason: "Hybrid 800 has the highest faithfulness among 1 configs with n >= 10 and hit rate >= 70%." },
        rows: [
          {
            ...base,
            label: "Hybrid 800",
            kind: "rag",
            run_id: ragRun,
            run_status: "completed",
            retrieval: { hit_rate: 0.71, hit_rate_ci: [0.58, 0.81], mrr: 0.55, context_precision: 0.4 },
            generation: { faithfulness: 0.9, n_judged: 12, hallucination_rate: 0.08, hallucination_ci: [0.02, 0.2], answer_correct_rate: 0.8, refusal_correct_rate: 1, skipped: { local_only: 3 } },
            latency_ms: { retrieval_p50: 42, retrieval_p95: 120, turn_p50: 900, turn_p95: 1500 },
            tokens_per_conversation: { agent_input: 1800, agent_output: 220, query_embedding: 60, rerank: 0 },
            cost_per_conversation_inr: null,
            token_savings_vs_full_context_pct: 91,
          },
          { ...base, label: "No RAG", kind: "no_rag", run_id: noRagRun, run_status: "completed", tokens_per_conversation: { agent_input: 500, agent_output: 200, query_embedding: 0, rerank: 0 } },
          { label: "Full context", kind: "full_context", run_id: null, n_calls: 0, n_questions_with_truth: 0, status_note: "n/a: KB is 520000 chars, limit 400000" },
        ],
      };
    });
    await expect(page.getByRole("region", { name: "Recommendation" })).toContainText("Hybrid 800 has the highest faithfulness among 1 configs with n >= 10 and hit rate >= 70%.");
    const table = page.getByRole("table", { name: "RAG report, one row per setup" });
    await expect(table.getByText("71% (58–81%)")).toBeVisible();
    await expect(table.getByText("8% (2–20%)")).toBeVisible();
    await expect(table.getByText("n/a: KB is 520000 chars, limit 400000")).toBeVisible();
    await expect(table.getByText("skipped: local_only ×3")).toBeVisible();
    await expect(table.getByText("91% fewer tokens")).toBeVisible();
    await expect(table.getByRole("link", { name: "Compare to no-RAG" })).toHaveAttribute("href", `/runs/compare?base=${noRagRun}&head=${ragRun}`);
    await expect(page.getByRole("img", { name: /Retrieval time per turn/ })).toBeVisible();
  });
});
