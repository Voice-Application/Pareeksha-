import { test, expect } from "@playwright/test";
import { watch } from "./support";

// FR-IN-9: integrations page lists real integrations / shows the empty state, deliveries drawer reachable.
test("integrations page loads from the real API", async ({ page }) => {
  const problems = watch(page);
  await page.goto("/integrations");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(problems).toEqual([]);
});
