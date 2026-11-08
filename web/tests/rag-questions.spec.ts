import { readFile } from "node:fs/promises";
import { test, expect, type Page } from "@playwright/test";
import { agent, freshState, mockApi, scenario, uuid, type MockState } from "./support/mock-api";

const kbId = uuid(500);
const agentId = uuid(150);
const docA = uuid(520);
const docB = uuid(521);
const ts = "2026-10-20T10:00:00Z";
const kb = { id: kbId, name: "Loan policy", description: "FAQ", local_only: false, has_secrets: false, created_at: ts, updated_at: ts };
const doc = (id: string, filename: string) => ({ id, filename, mime: "text/plain", char_count: 4200, sha256: "a".repeat(64), created_at: ts });
const answerable = (source_document_id: string, reference_answer: string) => ({ source_document_id, source_span: [10, 52] as [number, number], reference_answer, answerable: true });
const unanswerable = { source_document_id: null, source_span: null, reference_answer: "", answerable: false };

/** A prompt agent, a knowledge base with two documents, and `mutate` on top. */
async function open(page: Page, mutate?: (s: MockState) => void) {
  const state = freshState();
  state.agents.push(agent(50, { adapter: "prompt", name: "Prompt Bot" }));
  state.rag.kbs.push({ ...kb });
  state.rag.docs[kbId] = [doc(docA, "loan-policy.md"), doc(docB, "fees.txt")];
  mutate?.(state);
  await mockApi(page, state);
  await page.goto(`/knowledge-bases/${kbId}`);
  return state;
}

test.describe("Knowledge base questions", () => {
  test("lists the questions on this knowledge base's documents and every unanswerable one", async ({ page }) => {
    await open(page, (s) => {
      s.scenarios.push(
        scenario(10, { title: "What is the late fee?", agent_id: agentId, tags: ["rag", "answerable"], rag_expectation: answerable(docB, "2 percent of the EMI.") }),
        scenario(11, { title: "Can I pay in bitcoin?", agent_id: agentId, tags: ["rag", "unanswerable"], rag_expectation: unanswerable }),
        scenario(12, { title: "Question on another knowledge base", tags: ["rag", "answerable"], rag_expectation: answerable(uuid(999), "x") }),
      );
    });
    const table = page.getByRole("table", { name: "Questions" });
    await expect(table.getByRole("row")).toHaveCount(3);
    const late = table.getByRole("row").filter({ hasText: "What is the late fee?" });
    await expect(late).toContainText("answerable");
    await expect(late).toContainText("fees.txt");
    await expect(late).toContainText("2 percent of the EMI.");
    await expect(late).toContainText("Prompt Bot");
    await expect(table.getByRole("row").filter({ hasText: "Can I pay in bitcoin?" })).toContainText("unanswerable");
    await expect(table).not.toContainText("Question on another knowledge base");
    await expect(page.getByText("cannot tell which knowledge base they were written for")).toBeVisible();
  });

  test("generate: drafts are polled, reviewed and the kept ones saved as rag scenarios", async ({ page }) => {
    const s = await open(page, (st) => {
      st.draftRequest = { kind: "rag", kb_id: kbId, count: 3, unanswerable_share: 0.2, unmatched: 1 };
      st.draftResult = {
        status: "ready",
        drafts: [
          { agent_id: agentId, title: "How many days of grace are there?", caller_goal: "Ask the agent: How many days of grace are there?", success_criteria: "Five days.", tags: ["rag", "answerable"], max_turns: 4, reveal_rules: "", caller_speaks_first: false, rag_expectation: answerable(docA, "Five days.") },
          { agent_id: agentId, title: "Do you lend to Martians?", caller_goal: "Ask the agent: Do you lend to Martians?", success_criteria: "The agent says it does not have that information.", tags: ["rag", "unanswerable"], max_turns: 4, reveal_rules: "", caller_speaks_first: false, rag_expectation: unanswerable },
        ],
      };
    });
    await expect(page.getByText("No questions for this knowledge base yet.")).toBeVisible();
    await page.getByLabel("How many").fill("3");
    await page.getByRole("button", { name: "Generate questions" }).click();

    const sheet = page.getByRole("dialog", { name: "Review generated questions" });
    await expect(sheet.getByText("Generating 3 questions from the documents.")).toBeVisible();
    const post = s.calls.find((c) => c.method === "POST" && c.path === `/knowledge-bases/${kbId}/questions:generate`);
    expect(post?.body).toEqual({ agent_id: agentId, count: 3, unanswerable_share: 0.2 });

    await expect(sheet.getByText("passed the checks")).toContainText("2 of 3 questions passed the checks. 1 was dropped because the quote was not found in the document.");
    const grace = sheet.getByRole("listitem").filter({ hasText: "How many days of grace are there?" });
    await expect(grace).toContainText("loan-policy.md");
    await expect(grace).toContainText("Expected answer: Five days.");
    await expect(sheet.getByRole("listitem").filter({ hasText: "Do you lend to Martians?" })).toContainText("not in the knowledge base");

    await sheet.getByRole("checkbox", { name: "Keep question: Do you lend to Martians?" }).uncheck();
    await sheet.getByRole("button", { name: "Save 1 selected" }).click();
    await expect(page.getByText("Saved 1 question.")).toBeVisible();
    await expect(sheet).toBeHidden();
    const bulk = s.calls.find((c) => c.method === "POST" && c.path === "/scenarios:bulk")?.body as { source: string; scenarios: { title: string; rag_expectation: unknown }[] };
    expect(bulk.source).toBe("generated");
    expect(bulk.scenarios).toHaveLength(1);
    expect(bulk.scenarios[0]).toMatchObject({ title: "How many days of grace are there?", rag_expectation: { source_document_id: docA, source_span: [10, 52], answerable: true } });
    await expect(page.getByRole("table", { name: "Questions" }).getByText("How many days of grace are there?")).toBeVisible();
  });

  test("generate: invalid count, the API's local_only refusal, and a local-only knowledge base", async ({ page }) => {
    const s = await open(page, (st) => st.fail.push({ match: `POST /knowledge-bases/${kbId}/questions:generate`, status: 409, code: "local_only", message: "Knowledge base is local-only: the platform LLM cannot read it" }));
    await page.getByLabel("How many").fill("51");
    await page.getByRole("button", { name: "Generate questions" }).click();
    await expect(page.getByText("Use a whole number from 1 to 50.")).toBeVisible();
    await expect(page.getByLabel("How many")).toBeFocused();
    expect(s.calls.some((c) => c.path.endsWith("/questions:generate"))).toBe(false);

    await page.getByLabel("How many").fill("5");
    await page.getByRole("button", { name: "Generate questions" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Could not start generation." })).toContainText("Knowledge base is local-only: the platform LLM cannot read it. Import your own questions from a CSV instead");
    await expect(page.getByRole("dialog", { name: "Review generated questions" })).toBeHidden();

    s.rag.kbs[0].local_only = true;
    await page.reload();
    await expect(page.getByRole("button", { name: "Generate questions" })).toBeDisabled();
    await expect(page.getByText("This knowledge base is local only, so the platform LLM may not read it.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Import questions" })).toBeEnabled();
  });

  test("import: example CSV download, created count and the skipped rows in plain words", async ({ page }) => {
    const s = await open(page, (st) => {
      st.rag.questionImport = {
        result: { created: 2, unmatched: [{ row: 2, reason: "quote_not_found" }, { row: 4, reason: "document_not_found" }] },
        adds: [scenario(20, { title: "Is there a prepayment charge?", agent_id: agentId, tags: ["rag", "answerable"], rag_expectation: answerable(docA, "No.") })],
      };
    });
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download example CSV" }).click()]);
    expect(download.suggestedFilename()).toBe("questions-example.csv");
    const csv = await readFile(await download.path(), "utf8");
    expect(csv.split("\r\n")[0]).toBe("question,expected_answer,source_document,source_quote");
    expect(csv).toContain("loan-policy.md");

    await page.getByRole("button", { name: "Import questions" }).click();
    await expect(page.getByText("Choose a CSV file.")).toBeVisible();
    expect(s.rag.questionImportBodies).toHaveLength(0);

    await page.getByLabel("CSV file").setInputFiles({ name: "questions.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
    await page.getByRole("button", { name: "Import questions" }).click();
    await expect(page.getByRole("status").filter({ hasText: "created" })).toHaveText("2 questions created. 2 rows were skipped.");
    const skipped = page.getByRole("table", { name: "Skipped rows" });
    await expect(skipped.getByRole("row").filter({ hasText: "line 3 of the file" })).toContainText("The source_quote text is not in that document.");
    await expect(skipped.getByRole("row").filter({ hasText: "line 5 of the file" })).toContainText("No document in this knowledge base has the file name given in source_document.");
    expect(s.rag.questionImportBodies[0]).toContain(agentId);
    expect(s.rag.questionImportBodies[0]).toContain('filename="questions.csv"');
    await expect(page.getByRole("table", { name: "Questions" }).getByText("Is there a prepayment charge?")).toBeVisible();
  });

  test("import: the API's CSV error is shown", async ({ page }) => {
    await open(page, (st) => st.fail.push({ match: `POST /knowledge-bases/${kbId}/questions:import`, status: 422, code: "validation_error", message: "missing columns: source_quote" }));
    await page.getByLabel("CSV file").setInputFiles({ name: "bad.csv", mimeType: "text/csv", buffer: Buffer.from("question,expected_answer\nA,B\n") });
    await page.getByRole("button", { name: "Import questions" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Could not import." })).toContainText("missing columns: source_quote");
  });
});
