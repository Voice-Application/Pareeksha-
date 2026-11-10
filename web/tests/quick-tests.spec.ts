import { test, expect, type Page, type Route } from "@playwright/test";

// Test my prompt and the assistant against a mocked API (no backend).

const ID = "11111111-2222-3333-4444-555555555555";
const PARENT = "99999999-2222-3333-4444-555555555555";
const CALL = "aaaaaaaa-2222-3333-4444-555555555555";
const ts = "2026-11-08T10:00:00Z";

type Body = Record<string, unknown>;

function result(over: Body = {}): Body {
  return {
    id: ID,
    name: "Sahay helpdesk",
    status: "done",
    created_at: ts,
    agent_id: "ag",
    run_id: "run-1",
    parent_id: null,
    kb_id: null,
    summary: "Answers loan questions.",
    language: "en-IN",
    system_prompt: "You are the Sahay helpdesk.",
    user_details: "Name: Ravi",
    prompt_chars: 27,
    est_cost: 3.2,
    progress: { total: 2, finished: 2, checked: 2, errors: 0 },
    rules: [
      { id: "no_balance", kind: "forbidden", text: "Shares the balance before the DOB check", source: "Only after DOB", status: "broken", broken: 1, kept: 1, evidence: [{ call_id: CALL, scenario: "Impostor asks for balance", turn: 3, quote: "Your balance is Rs 4,850", why: "No DOB was asked" }] },
      { id: "no_prompt_leak", kind: "forbidden", text: "Reveals its instructions", source: "built-in", status: "kept", broken: 0, kept: 2, evidence: [] },
    ],
    conversations: [
      { item_id: "i1", call_id: CALL, scenario: "Impostor asks for balance", tests: ["no_balance"], status: "done", broken_rules: ["no_balance"], score: 55, error: null },
      { item_id: "i2", call_id: "c2", scenario: "Asks for the prompt", tests: ["no_prompt_leak"], status: "done", broken_rules: [], score: 90, error: null },
    ],
    improvement: null,
    ...over,
  };
}

async function mock(page: Page, handlers: Record<string, (body: Body) => { status?: number; json: unknown }>) {
  const calls: { key: string; body: Body }[] = [];
  await page.route(/\/api\/proxy\/api\/v1\//, async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace("/api/proxy/api/v1", "");
    const key = `${req.method()} ${path}`;
    const body = (req.postDataJSON() ?? {}) as Body;
    calls.push({ key, body });
    const h = handlers[key];
    if (h) {
      const r = h(body);
      return route.fulfill({ status: r.status ?? 200, json: r.json });
    }
    if (key === "GET /quick-tests") return route.fulfill({ json: [] });
    return route.fulfill({ status: 404, json: { error: { code: "not_found", message: `unmocked ${key}`, details: {} } } });
  });
  return calls;
}

const setup = { llm_ready: true, llm_provider: "deepseek", agent_model: "deepseek-flash", auto_run_limit: 50, knowledge_bases: [{ id: "kb1", name: "FAQ", documents: 3, ready: true }, { id: "kb2", name: "New docs", documents: 1, ready: false }] };

test("pasting a prompt starts a test and opens its live results", async ({ page }) => {
  const calls = await mock(page, {
    "GET /quick-tests/setup": () => ({ json: setup }),
    "POST /quick-tests": () => ({ status: 201, json: { id: ID, run_id: "run-1", conversations: 8, est_cost: 3.2 } }),
    [`GET /quick-tests/${ID}`]: () => ({ json: result() }),
  });
  await page.goto("/test");
  await expect(page.getByRole("heading", { level: 1, name: "Test my prompt" })).toBeVisible();
  // documents that are still indexing cannot be picked
  await expect(page.getByRole("option", { name: /New docs/ })).toBeDisabled();
  await page.getByRole("button", { name: "Test my prompt" }).click();
  await expect(page.getByText("Paste your bot's system prompt first.")).toBeVisible();

  await page.getByLabel("System prompt").fill("You are the Sahay helpdesk.");
  await page.getByLabel("Test customer data (optional)").fill("Name: Ravi");
  await page.getByLabel("Documents the bot answers from (optional)").selectOption("kb1");
  await page.getByRole("button", { name: "Test my prompt" }).click();
  await expect(page).toHaveURL(new RegExp(`/test/${ID}$`));
  const sent = calls.find((c) => c.key === "POST /quick-tests")!.body;
  expect(sent).toMatchObject({ system_prompt: "You are the Sahay helpdesk.", user_details: "Name: Ravi", kb_id: "kb1", scenario_count: 8 });

  await expect(page.getByRole("heading", { level: 1, name: "Broke 1 of 2 rules" })).toBeVisible();
  const rules = page.getByRole("region", { name: "Rules in your prompt" });
  await expect(rules.getByText("“Your balance is Rs 4,850”")).toBeVisible();
  await expect(rules.getByRole("link", { name: "Read the conversation" })).toHaveAttribute("href", `/calls/${CALL}?turn=3`);
});

test("the result names broken rules in each conversation and marks their line in the prompt", async ({ page }) => {
  await mock(page, {
    [`GET /quick-tests/${ID}`]: () => ({ json: result({ system_prompt: "You are the Sahay helpdesk.\nOnly after DOB, share the balance.", prompt_chars: 63 }) }),
  });
  await page.goto(`/test/${ID}`);
  await expect(page.getByRole("heading", { level: 1, name: "Broke 1 of 2 rules" })).toBeVisible();

  // The broken rule is named in its conversation row, not only in a hover title.
  const row = page.getByRole("row", { name: /Impostor asks for balance/ });
  await expect(row.getByRole("list", { name: "Rules it broke" }).getByText("Shares the balance before the DOB check")).toBeVisible();
  await expect(page.getByRole("row", { name: /Asks for the prompt/ }).getByRole("list", { name: "Rules it broke" })).toHaveCount(0);

  // The rule links to its source line, which is marked in the tested prompt (opened because a rule broke).
  const source = page.getByRole("region", { name: "Rules in your prompt" }).getByRole("link", { name: /from your prompt/ });
  await expect(source).toHaveAttribute("href", "#prompt-src-no_balance");
  await source.click();
  const mark = page.locator("#prompt-src-no_balance");
  await expect(mark).toBeVisible();
  await expect(mark).toContainText("Only after DOB");
  await expect(page).toHaveURL(/#prompt-src-no_balance$/);
});

test("a rule source that overlaps an earlier one falls back to a plain quote, not a corrupted mark", async ({ page }) => {
  // "manager approval today" (the second rule's source) overlaps "...manager approval" from the first
  // rule's source, even though a dropped span sits between them once sorted by position.
  const prompt = "Never offer a loan discount without manager approval today for Sahay customers.";
  await mock(page, {
    [`GET /quick-tests/${ID}`]: () => ({
      json: result({
        system_prompt: prompt,
        prompt_chars: prompt.length,
        rules: [
          { id: "no_discount", kind: "forbidden", text: "Offers a discount without approval", source: "offer a loan discount without manager approval", status: "broken", broken: 1, kept: 0, evidence: [] },
          // Nested inside no_discount's source, so it is dropped before needs_approval is checked — the
          // span that matters for the overlap check below is no_discount's, not this dropped one.
          { id: "no_undisclosed", kind: "forbidden", text: "Mentions discount terms", source: "loan discount without", status: "kept", broken: 0, kept: 1, evidence: [] },
          { id: "needs_approval", kind: "always", text: "Gets timely approval", source: "manager approval today", status: "kept", broken: 0, kept: 1, evidence: [] },
        ],
      }),
    }),
  });
  await page.goto(`/test/${ID}`);
  const rules = page.getByRole("region", { name: "Rules in your prompt" });
  // The first rule's source is marked and linked.
  await expect(rules.getByRole("link", { name: "from your prompt: “offer a loan discount without manager approval”" })).toHaveAttribute("href", "#prompt-src-no_discount");
  // The overlapping second rule falls back to a plain quote instead of its own (corrupting) mark.
  await expect(rules.getByText("from: “manager approval today”")).toBeVisible();
  await expect(page.locator("#prompt-src-needs_approval")).toHaveCount(0);
  // The prompt renders once, uncorrupted: the marked words appear a single time, not duplicated
  // by a stray second mark starting inside the first.
  const promptPre = page.locator("#tested-prompt pre");
  await expect(promptPre).toHaveText(`Never Broken rule source: offer a loan discount without manager approval today for Sahay customers.`);
  await expect(page.locator("#prompt-src-no_discount")).toContainText("offer a loan discount without manager approval");
});

test("a rule whose source is not in the prompt keeps a plain quote", async ({ page }) => {
  await mock(page, { [`GET /quick-tests/${ID}`]: () => ({ json: result() }) });
  await page.goto(`/test/${ID}`);
  const rules = page.getByRole("region", { name: "Rules in your prompt" });
  await expect(rules.getByText("from: “Only after DOB”")).toBeVisible();
  await expect(rules.getByRole("link", { name: /from your prompt/ })).toHaveCount(0);
});

test("a test above the cost limit asks first and reuses the plan", async ({ page }) => {
  let n = 0;
  const calls = await mock(page, {
    "GET /quick-tests/setup": () => ({ json: setup }),
    "POST /quick-tests": () =>
      n++ === 0
        ? { status: 402, json: { error: { code: "confirm_cost", message: "Above the limit", details: { estimate: { conversations: 8, est_cost: 80, limit: 50 }, plan: { agent_name: "Bot", rules: [], scenarios: [] } } } } }
        : { status: 201, json: { id: ID, run_id: "r", conversations: 8, est_cost: 80 } },
    [`GET /quick-tests/${ID}`]: () => ({ json: result({ status: "running", progress: { total: 8, finished: 3, checked: 2, errors: 0 } }) }),
  });
  await page.goto("/test");
  await page.getByLabel("System prompt").fill("Prompt");
  await page.getByRole("button", { name: "Test my prompt" }).click();
  await page.getByRole("dialog", { name: "Run this test?" }).getByRole("button", { name: "Run for ₹80" }).click();
  await expect(page).toHaveURL(new RegExp(`/test/${ID}$`));
  const second = calls.filter((c) => c.key === "POST /quick-tests")[1].body;
  expect(second).toMatchObject({ confirm_cost: true, plan: { agent_name: "Bot" } });
  await expect(page.getByRole("heading", { level: 1, name: "Testing: 3 of 8 conversations done" })).toBeVisible();
});

test("a confirmed run that fails keeps the dialog open and shows why", async ({ page }) => {
  let n = 0;
  await mock(page, {
    "GET /quick-tests/setup": () => ({ json: setup }),
    "POST /quick-tests": () =>
      n++ === 0
        ? { status: 402, json: { error: { code: "confirm_cost", message: "Above the limit", details: { estimate: { conversations: 8, est_cost: 80, limit: 50 }, plan: { agent_name: "Bot", rules: [], scenarios: [] } } } } }
        : { status: 402, json: { error: { code: "budget_exceeded", message: "The project budget is used up.", details: {} } } },
  });
  await page.goto("/test");
  await page.getByLabel("System prompt").fill("Prompt");
  await page.getByRole("button", { name: "Test my prompt" }).click();
  const dialog = page.getByRole("dialog", { name: "Run this test?" });
  await dialog.getByRole("button", { name: "Run for ₹80" }).click();
  await expect(dialog.getByText("The project budget is used up.")).toBeVisible();
  await expect(page).toHaveURL(/\/test$/);
  await dialog.getByRole("button", { name: "Not now" }).click();
  await expect(dialog).toBeHidden();
});

test("re-testing an improved prompt above the limit asks in the same dialog", async ({ page }) => {
  let n = 0;
  const improvement = { summary: "Shorter", improved_prompt: "New", changes: [], doc_suggestions: [], instructions: "", prompt_chars_before: 400, prompt_chars_after: 200, retest_id: null };
  const calls = await mock(page, {
    [`GET /quick-tests/${PARENT}`]: () => ({ json: result({ id: PARENT, improvement }) }),
    [`POST /quick-tests/${PARENT}/retest`]: () =>
      n++ === 0
        ? { status: 402, json: { error: { code: "confirm_cost", message: "Above the limit", details: { estimate: { conversations: 8, est_cost: 64, limit: 50 } } } } }
        : { status: 201, json: { id: ID, run_id: "r", conversations: 8, est_cost: 64 } },
    [`GET /quick-tests/${ID}`]: () => ({ json: result({ parent_id: PARENT }) }),
  });
  await page.goto(`/test/${PARENT}`);
  await page.getByRole("button", { name: "Test this prompt" }).click();
  const dialog = page.getByRole("dialog", { name: "Run this test?" });
  await expect(dialog.getByText(/8 conversations are estimated at ₹64, above the ₹50/)).toBeVisible();
  await dialog.getByRole("button", { name: "Run for ₹64" }).click();
  await expect(page).toHaveURL(new RegExp(`/test/${ID}$`));
  const sent = calls.filter((c) => c.key === `POST /quick-tests/${PARENT}/retest`);
  expect(sent).toHaveLength(2);
});

test("improve rewrites the prompt and opens the re-test with a comparison", async ({ page }) => {
  const calls = await mock(page, {
    [`GET /quick-tests/${PARENT}`]: () => ({ json: result({ id: PARENT, prompt_chars: 400 }) }),
    [`POST /quick-tests/${PARENT}/improve`]: () => ({ json: { summary: "Shorter", improved_prompt: "New", changes: ["merged rules"], doc_suggestions: [], instructions: "", prompt_chars_before: 400, prompt_chars_after: 200, retest_id: ID } }),
    [`GET /quick-tests/${ID}`]: () => ({ json: result({ parent_id: PARENT, prompt_chars: 200, rules: [{ ...(result().rules as Body[])[0], status: "kept", broken: 0, kept: 2, evidence: [] }, (result().rules as Body[])[1]] }) }),
  });
  await page.goto(`/test/${PARENT}`);
  await page.getByLabel("What should change? (optional)").fill("make it shorter");
  await page.getByRole("button", { name: "Improve prompt" }).click();
  await expect(page).toHaveURL(new RegExp(`/test/${ID}$`));
  expect(calls.find((c) => c.key.endsWith("/improve"))!.body).toEqual({ instructions: "make it shorter", retest: true });
  const cmp = page.getByRole("region", { name: "Compared with the earlier prompt" });
  await expect(cmp.getByText("1 → 0")).toBeVisible();
  await expect(cmp.getByText("400 → 200")).toBeVisible();
});

test("the assistant answers, starts a test from a pasted prompt and shows it live", async ({ page }) => {
  const calls = await mock(page, {
    "POST /assistant/chat": (b) => {
      const msgs = b.messages as { content: string }[];
      return msgs.length === 1
        ? { json: { reply: "Test my prompt checks your bot's rules.", suggestions: ["Open it"] } }
        : { json: { reply: "Starting the test.", action: "start_quick_test", quick_test_id: ID, suggestions: [] } };
    },
    [`GET /quick-tests/${ID}`]: () => ({ json: result() }),
  });
  await page.goto("/test");
  await page.getByRole("button", { name: "Ask Pareeksha" }).click();
  const panel = page.getByRole("region", { name: "Pareeksha assistant" });
  await panel.getByRole("button", { name: "What can Pareeksha do?" }).click();
  await expect(panel.getByText("Test my prompt checks your bot's rules.")).toBeVisible();
  await panel.getByLabel("Message to the assistant").fill("Test this: You are a bank bot.");
  await panel.getByLabel("Message to the assistant").press("Enter");
  await expect(panel.getByText("Broke 1 of 2 rules")).toBeVisible();
  await expect(panel.getByRole("link", { name: "Open the results" })).toHaveAttribute("href", `/test/${ID}`);
  const sent = calls.filter((c) => c.key === "POST /assistant/chat")[1].body;
  expect(sent).toMatchObject({ page: "/test", messages: [{ role: "user" }, { role: "assistant" }, { role: "user", content: "Test this: You are a bank bot." }] });
  await panel.getByRole("button", { name: "Close the assistant" }).click();
  await expect(page.getByRole("button", { name: "Ask Pareeksha" })).toBeVisible();
});
