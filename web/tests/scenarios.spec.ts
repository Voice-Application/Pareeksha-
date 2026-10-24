import { test, expect, type Page } from "@playwright/test";
import { freshState, mockApi, uuid, type MockState } from "./support/mock-api";

async function open(page: Page, path: string, mutate?: (s: MockState) => void) {
  const state = freshState();
  mutate?.(state);
  await mockApi(page, state);
  await page.goto(path);
  return state;
}

test.describe("Scenarios list", () => {
  test("loading skeleton, then rows with source chips and a link for promoted scenarios", async ({ page }) => {
    await open(page, "/scenarios", (s) => (s.delay = 700));
    await expect(page.getByRole("heading", { level: 1, name: "Scenarios", exact: true })).toBeVisible();
    await expect(page.getByRole("status", { name: "Loading scenarios" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Already paid, wants confirmation" })).toBeVisible();
    const promoted = page.getByRole("row", { name: /Promoted: wrong amount/ });
    await expect(promoted).toContainText("promoted");
    await expect(promoted.getByRole("link", { name: /call 00000000/ })).toHaveAttribute("href", `/calls/${uuid(900)}`);
    await expect(page.getByText("3 scenarios", { exact: true })).toBeVisible();
    // Used-in is not reported by the API yet: a dash, not a made-up number.
    await expect(page.getByRole("row", { name: /Abusive caller/ })).toContainText("-");
  });

  test("two header actions: Generate with AI is secondary, New scenario is the one primary", async ({ page }) => {
    await open(page, "/scenarios");
    await expect(page.getByRole("link", { name: "New scenario" })).toHaveAttribute("href", "/scenarios/new");
    await expect(page.getByRole("button", { name: "Generate with AI" })).toBeVisible();
  });

  test("filters by agent and tag using server-side params, source in the client", async ({ page }) => {
    const s = await open(page, "/scenarios");
    await page.getByLabel("Tag", { exact: true }).selectOption("adversarial");
    await expect.poll(() => s.calls.map((c) => `${c.path}?${c.query.toString()}`)).toContain("/scenarios?tag=adversarial&limit=50");
    await expect(page.getByRole("link", { name: "Abusive caller" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Already paid, wants confirmation" })).toHaveCount(0);
    await page.getByRole("button", { name: "Clear", exact: true }).click();
    await page.getByLabel("Source", { exact: true }).selectOption("promoted");
    await expect(page.getByRole("link", { name: "Promoted: wrong amount" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Abusive caller" })).toHaveCount(0);
  });

  test("filtered empty and first-use empty states", async ({ page }) => {
    await open(page, "/scenarios?q=nothing-matches");
    await expect(page.getByText("No scenarios match these filters")).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.getByRole("link", { name: "Abusive caller" })).toBeVisible();
  });

  test("first-use empty offers New scenario and Generate with AI", async ({ page }) => {
    await open(page, "/scenarios", (s) => (s.scenarios = []));
    await expect(page.getByRole("heading", { name: "No scenarios yet" })).toBeVisible();
    await expect(page.getByText("A scenario tells the synthetic caller what to try.")).toBeVisible();
    await expect(page.getByRole("main").getByRole("link", { name: "New scenario" })).toHaveCount(2);
  });

  test("error state with Retry", async ({ page }) => {
    const s = await open(page, "/scenarios", (st) => (st.fail = [{ match: "GET /scenarios", status: 500, message: "Query failed." }]));
    const alert = page.getByRole("alert").filter({ hasText: "Could not load scenarios" });
    await expect(alert).toContainText("Query failed.");
    s.fail = [];
    await alert.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByRole("link", { name: "Abusive caller" })).toBeVisible();
  });

  test("duplicate creates a copy", async ({ page }) => {
    const s = await open(page, "/scenarios");
    await page.getByRole("button", { name: "Actions for Abusive caller" }).click();
    await page.getByRole("menuitem", { name: "Duplicate" }).click();
    await expect(page.getByRole("link", { name: "Abusive caller (copy)" })).toBeVisible();
    expect(s.scenarios.some((x) => x.title === "Abusive caller (copy)")).toBe(true);
  });

  test("delete confirms by name; a 409 lists the runs that use the scenario", async ({ page }) => {
    await open(page, "/scenarios", (s) => (s.fail = [{ match: "DELETE /scenarios/", status: 409, code: "conflict", message: "This scenario is used by 1 run.", details: { runs: [{ id: uuid(700), name: "Nightly matrix" }] } }]));
    await page.getByRole("button", { name: "Actions for Abusive caller" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page.getByRole("dialog", { name: "Delete Abusive caller?" }).getByRole("button", { name: "Delete scenario" }).click();
    const dlg = page.getByRole("dialog", { name: "Abusive caller is in use" });
    await expect(dlg).toContainText("used by 1 run");
    await expect(dlg.getByRole("link", { name: "Nightly matrix" })).toHaveAttribute("href", `/runs/${uuid(700)}`);
  });

  test("delete succeeds when unused", async ({ page }) => {
    const s = await open(page, "/scenarios");
    await page.getByRole("button", { name: "Actions for Abusive caller" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete scenario" }).click();
    await expect(page.getByRole("link", { name: "Abusive caller" })).toHaveCount(0);
    expect(s.scenarios).toHaveLength(2);
  });
});

test.describe("Scenario editor", () => {
  test("validation: required fields are flagged on blur and on save", async ({ page }) => {
    await open(page, "/scenarios/new");
    await page.locator("#sc-title").focus();
    await page.locator("#sc-title").blur();
    await expect(page.getByText("Enter a title.")).toBeVisible();
    await page.getByRole("button", { name: "Create scenario" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Fix 3 fields before saving." })).toBeVisible();
    await expect(page.locator("#sc-title")).toBeFocused();
    await page.locator("#sc-turns").fill("1");
    await expect(page.getByText("Use a whole number from 2 to 40.").first()).toBeVisible();
  });

  test("create posts typed fixtures, tool order and tags", async ({ page }) => {
    const s = await open(page, "/scenarios/new");
    await page.locator("#sc-title").fill("Caller asks for a callback");
    await page.locator("#sc-goal").fill("Ask the agent to call back tomorrow.");
    await page.locator("#sc-success").fill("Agent offers a time and confirms it politely.");
    await page.getByRole("button", { name: "Add fact" }).click();
    await page.getByLabel("Facts name 1").fill("emi_amount");
    await page.getByLabel("Facts value 1").fill("4000");
    await page.getByLabel("Tags", { exact: true }).fill("edge_case");
    await page.keyboard.press("Enter");
    await page.getByLabel("Agent", { exact: true }).selectOption(uuid(101));
    await page.getByRole("button", { name: "Add tool" }).click();
    await page.getByRole("combobox", { name: "Tool 1" }).selectOption("record_promise_to_pay");
    await page.getByRole("button", { name: "Add tool" }).click();
    await page.getByRole("combobox", { name: "Tool 2" }).selectOption("transfer_to_human");
    await page.getByRole("switch", { name: "Required order" }).click();
    await page.getByRole("button", { name: "Create scenario" }).click();
    await expect(page).toHaveURL(/\/scenarios\/00000000-/);
    const post = s.calls.find((c) => c.method === "POST" && c.path === "/scenarios");
    expect(post?.body).toMatchObject({
      title: "Caller asks for a callback",
      fixtures: { emi_amount: 4000 },
      tags: ["edge_case"],
      max_turns: 12,
      agent_id: uuid(101),
      expected_tool_calls: [
        { name: "record_promise_to_pay", order: 1 },
        { name: "transfer_to_human", order: 2 },
      ],
    });
  });

  test("the judge preview lists criteria as a checklist and warns without blocking", async ({ page }) => {
    await open(page, "/scenarios/new");
    await page.locator("#sc-goal").fill("Say you paid UTR-555-0100 yesterday.");
    await page.locator("#sc-success").fill("Short");
    const panel = page.getByRole("region", { name: "How the judge will read this" });
    await expect(panel.getByRole("list", { name: "" }).first()).toBeVisible();
    await expect(panel).toContainText("Success criteria are shorter than 20 characters");
    await expect(panel).toContainText("No must-not-say rule");
    await expect(panel).toContainText("UTR-555-0100, which is not in the facts");
    await page.locator("#sc-success").fill("Agent asks for the UTR. Agent ends politely.");
    await expect(panel.getByText("Agent asks for the UTR.")).toBeVisible();
    await expect(panel.getByText("Agent ends politely.")).toBeVisible();
    await expect(panel).not.toContainText("shorter than 20 characters");
  });

  test("edit loads values, saves with PATCH and shows the promoted banner", async ({ page }) => {
    const s = await open(page, "/scenarios/" + uuid(202));
    await expect(page.getByText("Promoted from call")).toBeVisible();
    await expect(page.getByRole("link", { name: /#00000000/ })).toHaveAttribute("href", `/calls/${uuid(900)}`);
    await expect(page.locator("#sc-title")).toHaveValue("Promoted: wrong amount");
    await page.locator("#sc-goal").fill("Ask why the amount differs from the SMS.");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved Promoted: wrong amount." })).toBeVisible();
    expect(s.calls.some((c) => c.method === "PATCH" && c.path === `/scenarios/${uuid(202)}`)).toBe(true);
    expect(s.scenarios.find((x) => x.id === uuid(202))?.source_call_id).toBe(uuid(900));
  });

  test("an unknown scenario is a page error", async ({ page }) => {
    await open(page, "/scenarios/" + uuid(999));
    await expect(page.getByRole("heading", { name: "This item does not exist or was deleted" })).toBeVisible();
  });
});

test.describe("Generate with AI", () => {
  test("setup keeps the mix summing to the count", async ({ page }) => {
    await open(page, "/scenarios");
    await page.getByRole("button", { name: "Generate with AI" }).click();
    const dlg = page.getByRole("dialog", { name: "Generate scenarios with AI" });
    await expect(dlg).toBeVisible();
    const sum = async () => (await dlg.locator("output").allTextContents()).map(Number).reduce((a, b) => a + b, 0);
    expect(await sum()).toBe(10);
    await dlg.getByLabel("Happy path").fill("8");
    expect(await sum()).toBe(10);
    await dlg.getByLabel("How many").fill("5");
    expect(await sum()).toBe(5);
  });

  test("generate, review, edit one draft, save the selected ones", async ({ page }) => {
    const s = await open(page, "/scenarios");
    await page.getByRole("button", { name: "Generate with AI" }).click();
    const dlg = page.getByRole("dialog", { name: "Generate scenarios with AI" });
    await dlg.getByRole("button", { name: "Generate", exact: true }).click();
    await expect(dlg.getByText(/Generating/)).toBeVisible();
    await expect(dlg.getByText("Customer disputes the late fee")).toBeVisible();
    // Partial: asked for 10, 2 came back.
    await expect(dlg.getByText(/2 of 10 drafts passed validation/)).toBeVisible();
    // Drafts are not saved yet.
    expect(s.scenarios).toHaveLength(3);
    await dlg.getByRole("button", { name: "Edit draft: Caller asks for a callback" }).click();
    const edit = page.getByRole("dialog", { name: "Edit draft" });
    await edit.getByLabel("Title").fill("Caller asks for a callback tomorrow");
    await edit.getByRole("button", { name: "Apply" }).click();
    await dlg.getByRole("checkbox", { name: "Keep draft: Customer disputes the late fee" }).uncheck();
    await dlg.getByRole("button", { name: "Save 1 selected" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved 1 scenario." })).toBeVisible();
    await expect(page.getByRole("link", { name: "Caller asks for a callback tomorrow" })).toBeVisible();
    const bulk = s.calls.find((c) => c.path === "/scenarios:bulk");
    expect(bulk?.body).toMatchObject({ source: "generated" });
  });

  test("closing with unsaved drafts asks to confirm", async ({ page }) => {
    await open(page, "/scenarios");
    await page.getByRole("button", { name: "Generate with AI" }).click();
    const dlg = page.getByRole("dialog", { name: "Generate scenarios with AI" });
    await dlg.getByRole("button", { name: "Generate", exact: true }).click();
    await expect(dlg.getByText("Customer disputes the late fee")).toBeVisible();
    await page.keyboard.press("Escape");
    const confirm = page.getByRole("dialog", { name: "Discard unsaved drafts?" });
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Discard drafts" }).click();
    await expect(dlg).toBeHidden();
  });

  test("a failed generation shows the error and Try again", async ({ page }) => {
    const s = await open(page, "/scenarios", (st) => (st.draftResult = { status: "failed", drafts: [], error: "Gemini returned invalid JSON twice." }));
    await page.getByRole("button", { name: "Generate with AI" }).click();
    const dlg = page.getByRole("dialog", { name: "Generate scenarios with AI" });
    await dlg.getByRole("button", { name: "Generate", exact: true }).click();
    await expect(dlg.getByRole("alert")).toContainText("Gemini returned invalid JSON twice.");
    await dlg.getByRole("button", { name: "Try again" }).click();
    await expect.poll(() => s.calls.filter((c) => c.path.endsWith("scenarios:generate")).length).toBe(2);
  });
});
