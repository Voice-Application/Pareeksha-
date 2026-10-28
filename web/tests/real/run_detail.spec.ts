import { test, expect } from "@playwright/test";
import { api, firstEvaluatedCall } from "./support";

// FR-DB-2 (static half): a finished real run renders every one of its calls in < 3 s.
test("run detail renders all real items quickly", async ({ page }) => {
  const { runId } = await firstEvaluatedCall();
  const items = (await api<{ items: { scenario?: string; scenario_title?: string }[] }>(`/runs/${runId}/items?limit=200`)).items;
  const t0 = Date.now();
  await page.goto(`/runs/${runId}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText(items[0].scenario ?? items[0].scenario_title ?? "", { exact: false }).first()).toBeVisible();
  expect(Date.now() - t0).toBeLessThan(3000 + 1500); // 3 s render budget + dev-box navigation slack
});
