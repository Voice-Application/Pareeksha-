import { test, expect } from "@playwright/test";
import { NAV_ITEMS } from "../../lib/nav";
import { api, firstEvaluatedCall, SHOTS, watch } from "./support";

type Page<T> = { items: T[] };

// FR-DB-1: every sidebar page loads against the real API with real data, no console errors, no 5xx.
const REAL_TEXT: Record<string, () => Promise<string>> = {
  "/agents": async () => (await api<Page<{ name: string }>>("/agents")).items[0].name,
  "/scenarios": async () => (await api<Page<{ title: string }>>("/scenarios")).items[0].title,
  "/personas": async () => (await api<Page<{ name: string }>>("/personas")).items[0].name,
  "/noise-profiles": async () => (await api<Page<{ name: string }>>("/noise-profiles")).items[0].name,
};

for (const item of NAV_ITEMS) {
  test(`real data: ${item.href}`, async ({ page }) => {
    const problems = watch(page);
    const res = await page.goto(item.href);
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    if (REAL_TEXT[item.href]) await expect(page.getByText(await REAL_TEXT[item.href](), { exact: false }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/Something went wrong|Application error/i)).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/page${item.href === "/" ? "-overview" : item.href.replace(/\//g, "-")}.png`, fullPage: true });
    expect(problems).toEqual([]);
  });
}

test("real data: run detail and call detail pages", async ({ page }) => {
  const { runId, callId } = await firstEvaluatedCall();
  const problems = watch(page);
  expect((await page.goto(`/runs/${runId}`))?.status()).toBe(200);
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `${SHOTS}/run-detail.png`, fullPage: true });
  expect((await page.goto(`/calls/${callId}`))?.status()).toBe(200);
  await page.waitForLoadState("networkidle");
  const call = await api<{ turns: { text: string }[] }>(`/calls/${callId}`);
  await expect(page.getByText(call.turns[0].text.slice(0, 20), { exact: false }).first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/call-detail.png`, fullPage: true });
  expect(problems).toEqual([]);
});
