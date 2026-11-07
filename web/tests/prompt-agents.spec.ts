import { test, expect, type Page } from "@playwright/test";
import { agent, freshState, mockApi, uuid, type MockState } from "./support/mock-api";

async function open(page: Page, path: string, mutate?: (s: MockState) => void) {
  const state = freshState();
  mutate?.(state);
  await mockApi(page, state);
  await page.goto(path);
  return state;
}

const pid = uuid(150);
const promptAgent = (over = {}) => (s: MockState) => void s.agents.push(agent(50, { adapter: "prompt", name: "Prompt Bot", ...over }));

test.describe("Prompt agents", () => {
  test("create a prompt agent, save versions, see 'No changes' and the v1 to v2 diff", async ({ page }) => {
    const s = await open(page, "/agents/new");
    await page.getByRole("radio", { name: "Prompt (text)" }).click();
    await expect(page.getByLabel("Endpoint URL")).toHaveCount(0);
    await page.locator("#agent-name").fill("Prompt Bot");
    await page.getByLabel("Description").fill("Text agent for EMI reminders.");
    await page.getByLabel("API key").fill("sk-test-not-real");
    await page.getByRole("button", { name: "Create agent" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Prompt Bot" })).toBeVisible();
    const post = s.calls.find((c) => c.method === "POST" && c.path === "/agents");
    expect(post?.body).toMatchObject({ adapter: "prompt", glass_box: true, adapter_secrets: { api_key: "sk-test-not-real" } });
    expect(post?.body).not.toHaveProperty("endpoint_url");

    await page.getByLabel("Model").fill("gpt-4o-mini");
    await page.getByLabel("System prompt").fill("You are an EMI reminder agent.\nBe brief.\nNever threaten.");
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved v1" })).toBeVisible();

    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByRole("status").filter({ hasText: "No changes, still v1" })).toBeVisible();

    await page.getByLabel("System prompt").fill("You are an EMI reminder agent.\nBe brief.\nAlways confirm the amount.\nNever threaten.");
    await page.getByLabel("Version note").fill("confirm amount");
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved v2" })).toBeVisible();

    const diff = page.getByRole("region", { name: "System prompt", exact: true }).getByRole("table");
    await expect(diff.locator('tr[data-kind="add"]')).toHaveCount(1);
    await expect(diff.locator('tr[data-kind="add"]')).toContainText("Always confirm the amount.");
    await expect(diff.locator('tr[data-kind="del"]')).toHaveCount(0);
  });

  test("tools JSON is validated inline and an example can be added", async ({ page }) => {
    await open(page, "/agents/" + pid, promptAgent());
    await page.getByLabel("Tools (JSON)").fill('{"a": 1}');
    await page.getByLabel("Model").fill("gpt-4o-mini");
    await page.getByLabel("System prompt").fill("Hello");
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByText("Tools must be a JSON array")).toBeVisible();
    await expect(page.getByLabel("Tools (JSON)")).toHaveAttribute("aria-describedby", /pv-tools-error/);
    await page.getByLabel("Tools (JSON)").fill("[]");
    await page.getByRole("button", { name: "Add example tool" }).click();
    await expect(page.getByLabel("Tools (JSON)")).toHaveValue(/lookup_emi/);
    await page.getByLabel("Tools (JSON)").fill('[{"name":"a b","parameters":{"type":"object"}}]');
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByText(/name must be 1 to 64/)).toBeVisible();
  });

  test("a saved key shows 'Key saved' with a Replace key action and is never prefilled", async ({ page }) => {
    const s = await open(page, "/agents/" + pid, promptAgent({ has_adapter_secrets: true }));
    await expect(page.getByText("Key saved")).toBeVisible();
    await page.getByRole("button", { name: "Replace key" }).click();
    await expect(page.getByLabel("API key")).toHaveValue("");
    await expect(page.getByLabel("API key")).toHaveAttribute("type", "password");

    await page.getByLabel("API key").fill("sk-replacement-not-real");
    const response = page.waitForResponse((r) => r.request().method() === "PATCH" && r.url().endsWith(`/agents/${pid}`));
    await page.getByRole("button", { name: "Save changes" }).click();
    const saved = await (await response).json();
    const patch = s.calls.find((c) => c.method === "PATCH" && c.path === `/agents/${pid}`);
    expect(patch?.body).toMatchObject({ adapter_secrets: { api_key: "sk-replacement-not-real" } });
    expect(saved).not.toHaveProperty("adapter_secrets");
    expect(saved.has_adapter_secrets).toBe(true);
    await expect(page.getByText("Key saved")).toBeVisible();
    await expect(page.getByLabel("API key")).toHaveCount(0);
  });

  test("a private base URL error is shown on the field", async ({ page }) => {
    await open(page, "/agents/" + pid, (s) => {
      promptAgent()(s);
      s.fail.push({ match: "POST /agents/" + pid + "/prompt-versions", status: 422, code: "base_url_not_allowed" });
    });
    await page.getByLabel("Model").fill("llama3");
    await page.getByLabel("Base URL").fill("http://10.0.0.5:11434");
    await page.getByLabel("System prompt").fill("Hello");
    await page.getByRole("button", { name: "Save as new version" }).click();
    await expect(page.getByText(/private or internal address/).first()).toBeVisible();
  });
});
