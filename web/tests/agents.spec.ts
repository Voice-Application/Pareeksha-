import { test, expect, type Page } from "@playwright/test";
import { agent, freshState, mockApi, uuid, type MockState } from "./support/mock-api";

async function open(page: Page, path: string, mutate?: (s: MockState) => void) {
  const state = freshState();
  mutate?.(state);
  await mockApi(page, state);
  await page.goto(path);
  return state;
}

test.describe("Agents list", () => {
  test("shows a skeleton while loading, then the table", async ({ page }) => {
    await open(page, "/agents", (s) => (s.delay = 700));
    await expect(page.getByRole("heading", { level: 1, name: "Agents", exact: true })).toBeVisible();
    await expect(page.getByRole("status", { name: "Loading agents" })).toBeVisible();
    await expect(page.getByRole("link", { name: "EMI Reminder Bot" })).toBeVisible();
    await expect(page.getByRole("status", { name: "Loading agents" })).toHaveCount(0);
  });

  test("lists active agents with adapter, languages, glass-box, last run and connection", async ({ page }) => {
    await open(page, "/agents");
    const row = page.getByRole("row", { name: /EMI Reminder Bot/ });
    await expect(row).toContainText("audio_v1");
    await expect(row).toContainText("kn hi en");
    await expect(row).toContainText("yes");
    await expect(row.getByRole("link", { name: /ago|day|hour|minute|yesterday|now/ })).toBeVisible();
    await expect(row).toContainText("never tested");
    await expect(page.getByRole("link", { name: "Old Bot" })).toHaveCount(0);
    await expect(page.getByText("2 active", { exact: true })).toBeVisible();
    // The one primary action on the page.
    await expect(page.getByRole("link", { name: "Add agent" })).toHaveAttribute("href", "/agents/new");
  });

  test("show archived is a URL-backed switch", async ({ page }) => {
    await open(page, "/agents");
    await page.getByRole("switch", { name: "Show archived" }).click();
    await expect(page).toHaveURL(/archived=1/);
    await expect(page.getByRole("link", { name: "Old Bot" })).toBeVisible();
    await expect(page.getByText("2 active, 1 archived")).toBeVisible();
  });

  test("filters by adapter, shows a chip, and clears", async ({ page }) => {
    await open(page, "/agents");
    await page.getByLabel("Adapter", { exact: true }).selectOption("pipecat");
    await expect(page).toHaveURL(/adapter=pipecat/);
    await expect(page.getByRole("link", { name: "Collections Bot" })).toBeVisible();
    await expect(page.getByRole("link", { name: "EMI Reminder Bot" })).toHaveCount(0);
    await page.getByRole("button", { name: "Clear", exact: true }).click();
    await expect(page.getByRole("link", { name: "EMI Reminder Bot" })).toBeVisible();
  });

  test("filtered empty keeps the filter bar and offers Clear filters", async ({ page }) => {
    await open(page, "/agents?q=zzzz");
    await expect(page.getByText("No agents match these filters")).toBeVisible();
    await expect(page.getByRole("searchbox", { name: "Search agents" })).toHaveValue("zzzz");
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.getByRole("link", { name: "EMI Reminder Bot" })).toBeVisible();
  });

  test("first-use empty state has one primary action", async ({ page }) => {
    await open(page, "/agents", (s) => (s.agents = []));
    await expect(page.getByRole("heading", { name: "No agents yet" })).toBeVisible();
    await expect(page.getByText("make demo")).toBeVisible();
    await page.getByRole("main").getByRole("link", { name: "Add agent" }).last().click();
    await expect(page).toHaveURL(/\/agents\/new$/);
  });

  test("error state shows the cause and request id, and Retry recovers", async ({ page }) => {
    const s = await open(page, "/agents", (st) => (st.fail = [{ match: "GET /agents", status: 500, message: "Database is unavailable." }]));
    const alert = page.getByRole("alert").filter({ hasText: "Could not load agents" });
    await expect(alert).toContainText("Could not load agents");
    await expect(alert).toContainText("Database is unavailable.");
    await expect(alert).toContainText("req_test_0001");
    s.fail = [];
    await alert.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByRole("link", { name: "EMI Reminder Bot" })).toBeVisible();
  });

  test("load more fetches the next cursor page", async ({ page }) => {
    const s = await open(page, "/agents", (st) => (st.agents = Array.from({ length: 55 }, (_, i) => agent(i + 1, { name: `Bulk agent ${String(i + 1).padStart(2, "0")}` }))));
    await expect(page.getByText("50 loaded")).toBeVisible();
    await page.getByRole("button", { name: "Load more" }).click();
    await expect(page.getByText("55 loaded")).toBeVisible();
    expect(s.calls.filter((c) => c.path === "/agents" && c.query.get("cursor") === "50")).toHaveLength(1);
  });

  test("row menu works from the keyboard and runs a connection test", async ({ page }) => {
    await open(page, "/agents");
    const trigger = page.getByRole("button", { name: "Actions for EMI Reminder Bot" });
    await trigger.focus();
    await page.keyboard.press("Enter");
    const menu = page.getByRole("menu", { name: "Actions for EMI Reminder Bot" });
    await expect(menu).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Edit" })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(menu.getByRole("menuitem", { name: "Test connection" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(trigger).toBeFocused();

    await page.keyboard.press("Enter");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("row", { name: /EMI Reminder Bot/ })).toContainText("ok 820 ms");
    await expect(page.getByRole("status").filter({ hasText: "connected, first audio in 820 ms" })).toBeVisible();
  });

  test("a failed connection test shows the error word in the row", async ({ page }) => {
    await open(page, "/agents", (s) => (s.testConnection = { ok: false, error: "refused", detail: "connection refused" }));
    await page.getByRole("button", { name: "Actions for EMI Reminder Bot" }).click();
    await page.getByRole("menuitem", { name: "Test connection" }).click();
    await expect(page.getByRole("row", { name: /EMI Reminder Bot/ })).toContainText("refused");
  });

  test("archive asks to confirm, names the agent, then removes it", async ({ page }) => {
    const s = await open(page, "/agents");
    await page.getByRole("button", { name: "Actions for Collections Bot" }).click();
    await page.getByRole("menuitem", { name: "Archive" }).click();
    const dlg = page.getByRole("dialog", { name: "Archive Collections Bot?" });
    await expect(dlg).toContainText("keep their history");
    await dlg.getByRole("button", { name: "Archive agent" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Archived Collections Bot." })).toBeVisible();
    await expect(page.getByRole("link", { name: "Collections Bot" })).toHaveCount(0);
    expect(s.calls.some((c) => c.method === "POST" && c.path === `/agents/${uuid(102)}/archive`)).toBe(true);
  });

  test("a failed archive rolls back with a retry toast", async ({ page }) => {
    await open(page, "/agents", (s) => (s.fail = [{ match: "POST /agents/", status: 500, message: "Archive failed upstream." }]));
    await page.getByRole("button", { name: "Actions for Collections Bot" }).click();
    await page.getByRole("menuitem", { name: "Archive" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive agent" }).click();
    const toast = page.getByRole("alert").filter({ hasText: "Could not archive Collections Bot" });
    await expect(toast).toBeVisible();
    await expect(toast.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Collections Bot" })).toBeVisible();
  });
});

test.describe("Agent form", () => {
  test("create: empty submit shows an error summary and focuses the first invalid field", async ({ page }) => {
    await open(page, "/agents/new");
    await expect(page.getByRole("button", { name: "Test connection" })).toBeDisabled();
    await expect(page.getByText("Save the agent first.")).toBeVisible();
    await page.getByRole("button", { name: "Create agent" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Fix 3 fields before saving." })).toBeVisible();
    await expect(page.locator("#agent-name")).toBeFocused();
    await expect(page.getByText("Enter a name.").last()).toBeVisible();
  });

  test("create: fills the form, posts the typed payload and moves to the saved agent", async ({ page }) => {
    const s = await open(page, "/agents/new");
    await page.locator("#agent-name").fill("Billing Bot");
    await page.getByLabel("Description").fill("Answers billing questions in Hindi.");
    await page.getByLabel("Endpoint URL").fill("ws://billing:8765/ws");
    await page.getByRole("switch", { name: "Glass-box" }).click();
    await page.getByLabel("Max call seconds").fill("180");
    await page.getByRole("button", { name: "Add disclosure" }).click();
    await page.getByLabel("Id", { exact: true }).fill("recording");
    await page.getByLabel("Within turns").fill("2");
    await page.getByLabel("Text", { exact: true }).fill("This call is recorded");
    await page.getByLabel("Bias list").fill("EMI");
    await page.keyboard.press("Enter");
    await page.getByRole("button", { name: "Create agent" }).click();
    await expect(page).toHaveURL(/\/agents\/00000000-0000-4000-8000-/);
    const post = s.calls.find((c) => c.method === "POST" && c.path === "/agents");
    expect(post?.body).toMatchObject({
      name: "Billing Bot",
      adapter: "audio_v1",
      glass_box: true,
      max_call_seconds: 180,
      bias_list: ["EMI"],
      mandatory_disclosures: [{ id: "recording", text: "This call is recorded", regex: null, within_turns: 2 }],
    });
    await expect(page.getByRole("heading", { level: 1, name: "Billing Bot" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Test connection" })).toBeEnabled();
  });

  test("a duplicate name from the API is shown on the name field", async ({ page }) => {
    await open(page, "/agents/new");
    await page.locator("#agent-name").fill("EMI Reminder Bot");
    await page.getByLabel("Description").fill("Duplicate.");
    await page.getByLabel("Endpoint URL").fill("ws://x:1/ws");
    await page.getByRole("button", { name: "Create agent" }).click();
    await expect(page.getByText("An agent with this name already exists.").first()).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "Could not save" })).toBeVisible();
  });

  test("regex fields preview a phrase live and flag an invalid pattern", async ({ page }) => {
    await open(page, "/agents/new");
    await page.getByRole("button", { name: "Add disclosure" }).click();
    await page.getByLabel("Regex", { exact: true }).fill("(record|रिकॉर्ड)");
    await page.getByLabel("Try a phrase against regex").fill("this call is being recorded");
    await expect(page.getByRole("status").filter({ hasText: "match" })).toContainText("match");
    await page.getByLabel("Try a phrase against regex").fill("hello");
    await expect(page.getByRole("status").filter({ hasText: "no match" })).toBeVisible();
    await page.getByLabel("Regex", { exact: true }).fill("(unclosed");
    await expect(page.getByText(/This pattern is not valid:/)).toBeVisible();
  });

  test("duplicate disclosure ids are flagged on the row", async ({ page }) => {
    await open(page, "/agents/new");
    for (let i = 0; i < 2; i++) await page.getByRole("button", { name: "Add disclosure" }).click();
    const ids = page.getByLabel("Id", { exact: true });
    await ids.nth(0).fill("recording");
    await ids.nth(1).fill("recording");
    await page.locator("#agent-name").fill("X");
    await page.getByRole("button", { name: "Create agent" }).click();
    await expect(page.getByText("This id is used by another disclosure.").first()).toBeVisible();
  });

  test("unsupported adapters are disabled with a tooltip", async ({ page }) => {
    await open(page, "/agents/new");
    const vapi = page.getByRole("radio", { name: "vapi" });
    await expect(vapi).toBeDisabled();
    await expect(vapi).toHaveAttribute("title", /not supported in this build/);
    // Arrow keys skip disabled options and move selection like a radio group.
    await page.getByRole("radio", { name: "audio_v1" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("radio", { name: "pipecat" })).toBeChecked();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("radio", { name: "audio_v1" })).toBeChecked();
  });

  test("edit: loads the saved values and Save and test shows the pass strip", async ({ page }) => {
    await open(page, "/agents/" + uuid(101));
    await expect(page.locator("#agent-name")).toHaveValue("EMI Reminder Bot");
    await expect(page.getByLabel("Endpoint URL")).toHaveValue("ws://mock-agent:8765/ws");
    await page.getByRole("button", { name: "Save and test" }).click();
    const panel = page.getByRole("region", { name: "Connection test" });
    await expect(panel).toContainText("820 ms");
    await expect(panel).toContainText("pareeksha-audio-v1");
    await expect(panel).toContainText("seen");
  });

  test("a failed test shows the error word, detail and one suggested fix", async ({ page }) => {
    await open(page, "/agents/" + uuid(101), (s) => (s.testConnection = { ok: false, error: "timeout", detail: "no audio within 10000 ms" }));
    await page.getByRole("button", { name: "Test connection" }).click();
    const panel = page.getByRole("region", { name: "Connection test" });
    await expect(panel.getByRole("alert")).toContainText("timeout");
    await expect(panel.getByRole("alert")).toContainText("no audio within 10000 ms");
    await expect(panel.getByRole("alert")).toContainText("did not speak within 10 seconds");
  });

  test("editing after a test marks the result as stale", async ({ page }) => {
    await open(page, "/agents/" + uuid(101));
    await page.getByRole("button", { name: "Test connection" }).click();
    await expect(page.getByText("820 ms").first()).toBeVisible();
    await page.getByLabel("Endpoint URL").fill("ws://other:1/ws");
    await expect(page.getByText("Result is for the previous settings.")).toBeVisible();
  });

  test("an unknown agent shows a page error with a way back", async ({ page }) => {
    await open(page, "/agents/" + uuid(999));
    await expect(page.getByRole("heading", { name: "This item does not exist or was deleted" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to agents" })).toBeVisible();
  });

  test("an archived agent opens read-only with a banner", async ({ page }) => {
    await open(page, "/agents/" + uuid(103));
    await expect(page.getByText(/Archived on/)).toBeVisible();
    await expect(page.locator("#agent-name")).toBeDisabled();
    await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
  });

  test("leaving with unsaved changes asks first", async ({ page }) => {
    await open(page, "/agents/" + uuid(101));
    await page.locator("#agent-name").fill("Renamed");
    await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Personas" }).click();
    const dlg = page.getByRole("dialog", { name: "Leave without saving?" });
    await expect(dlg).toBeVisible();
    await dlg.getByRole("button", { name: "Cancel" }).click();
    await expect(page).toHaveURL(/\/agents\//);
    await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Personas" }).click();
    await page.getByRole("dialog", { name: "Leave without saving?" }).getByRole("button", { name: "Leave page" }).click();
    await expect(page).toHaveURL(/\/personas$/);
  });

  test("archive from the danger zone", async ({ page }) => {
    const s = await open(page, "/agents/" + uuid(102));
    await page.getByRole("button", { name: "Archive agent" }).first().click();
    const dlg = page.getByRole("dialog", { name: "Archive Collections Bot?" });
    await dlg.getByRole("button", { name: "Archive agent" }).click();
    await expect(page).toHaveURL(/\/agents$/);
    expect(s.agents.find((a) => a.id === uuid(102))?.archived).toBe(true);
  });
});
