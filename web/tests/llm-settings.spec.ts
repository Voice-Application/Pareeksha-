import { test, expect, type Page } from "@playwright/test";
import { freshState, mockApi } from "./support/mock-api";

type Llm = { provider: string; base_url: string | null; judge_model: string | null; caller_model: string | null; designer_model: string | null; api_key_set: boolean; api_key_last4: string | null; source: "project" | "environment" };
type Rec = { method: string; path: string; body: unknown };

/** Stateful stand-in for /settings/llm, layered over the shared mock (later routes win). */
async function open(page: Page, opts: { member?: boolean; testResult?: object } = {}) {
  let llm: Llm = { provider: "deepseek", base_url: null, judge_model: "deepseek-chat", caller_model: "deepseek-chat", designer_model: "deepseek-chat", api_key_set: false, api_key_last4: null, source: "environment" };
  const calls: Rec[] = [];
  await mockApi(page, freshState());
  await page.route(/\/api\/proxy\/api\/v1\/settings\/llm/, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace("/api/proxy/api/v1", "");
    const method = req.method();
    const body = req.postData() ? req.postDataJSON() : undefined;
    calls.push({ method, path, body });
    if (path.endsWith("/test")) return route.fulfill({ json: opts.testResult ?? { ok: true, provider: llm.provider, model: llm.judge_model, latency_ms: 412, error: null } });
    if (method === "PUT") {
      const { api_key, ...rest } = body as Llm & { api_key?: string };
      llm = { ...llm, ...rest, source: "project", api_key_set: !!api_key || llm.api_key_set, api_key_last4: api_key ? api_key.slice(-4) : llm.api_key_last4 };
    }
    return route.fulfill({ json: llm });
  });
  if (opts.member) await page.context().addCookies([{ name: "pareeksha_signed_in", value: "member", url: "http://127.0.0.1:3100" }]);
  await page.goto("/settings/llm");
  return calls;
}

test.describe("LLM settings", () => {
  test("loads the environment defaults with the source line", async ({ page }) => {
    await open(page);
    await expect(page.getByRole("heading", { level: 1, name: "LLM", exact: true })).toBeVisible();
    await expect(page.getByText("Using environment defaults (.env)")).toBeVisible();
    await expect(page.getByLabel("Judge model")).toHaveValue("deepseek-chat");
    await expect(page.getByRole("radio", { name: "DeepSeek" })).toBeChecked();
    await expect(page.getByLabel("Base URL")).toHaveCount(0);
  });

  test("openai_compatible reveals the base URL", async ({ page }) => {
    await open(page);
    await page.getByRole("radio", { name: "OpenAI-compatible" }).click();
    await expect(page.getByLabel("Base URL")).toBeVisible();
  });

  test("saving with a key sends it, then only the last four show", async ({ page }) => {
    const calls = await open(page);
    await page.getByLabel("API key").fill("sk-secret-wxyz");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Project setting")).toBeVisible();
    await expect(page.getByText("ends in ••••wxyz")).toBeVisible();
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ provider: "deepseek", api_key: "sk-secret-wxyz" });
    await expect(page.locator("body")).not.toContainText("sk-secret-wxyz");
    await expect(page.locator("input[type=password]")).toHaveCount(0);
    await page.getByRole("button", { name: "Replace" }).click();
    await expect(page.getByLabel("API key")).toHaveValue("");
  });

  test("a failed connection test shows the error text", async ({ page }) => {
    await open(page, { testResult: { ok: false, provider: "deepseek", model: "deepseek-chat", latency_ms: 90, error: "401 invalid api key" } });
    await page.getByRole("button", { name: "Test saved settings" }).click();
    await expect(page.getByText("401 invalid api key")).toBeVisible();
  });

  test("test is disabled while the form has unsaved changes", async ({ page }) => {
    await open(page);
    const btn = page.getByRole("button", { name: "Test saved settings" });
    await expect(btn).toBeEnabled();
    await page.getByLabel("Judge model").fill("other-model");
    await expect(btn).toBeDisabled();
    await expect(page.getByText("Save first to test these values")).toBeVisible();
  });

  test("a null latency is not rendered as null ms", async ({ page }) => {
    await open(page, { testResult: { ok: true, provider: "deepseek", model: "deepseek-chat", latency_ms: null, error: null } });
    await page.getByRole("button", { name: "Test saved settings" }).click();
    await expect(page.getByText(/Connected to/)).toBeVisible();
    await expect(page.locator("body")).not.toContainText("null ms");
  });

  test("a member session is read-only", async ({ page }) => {
    await open(page, { member: true });
    await expect(page.getByText(/Only an admin key can change/)).toBeVisible();
    await expect(page.getByLabel("Judge model")).toBeDisabled();
    await expect(page.getByRole("button", { name: "Save", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Revert to environment" })).toHaveCount(0);
  });
});
