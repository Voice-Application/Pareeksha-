import { test, expect } from "@playwright/test";
import { watch } from "./support";

// FR-DB-4: dialect page renders from the real API. With no ASR report in the stack it must show an honest empty state.
test("dialect page renders against the real API", async ({ page }) => {
  const problems = watch(page);
  await page.goto("/dialect");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(problems).toEqual([]);
});
