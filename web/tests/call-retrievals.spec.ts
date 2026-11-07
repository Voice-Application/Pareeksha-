import { test, expect } from "@playwright/test";
import { mockFe, opsState, CALL_ID } from "./support/fe03-mock";

test("retrieval card shows on the retrieving agent turn only, collapsed until expanded", async ({ page }) => {
  await mockFe(page, opsState());
  await page.goto(`/calls/${CALL_ID}`);
  const card = page.locator("#turn-2").getByTestId("retrieval-card");
  const toggle = card.getByRole("button", { name: /Retrieved 1 chunk · hybrid k=3 · 55 ms/ });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(card.getByText("The monthly EMI is four thousand rupees.")).toBeHidden();
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(card.getByText("The monthly EMI is four thousand rupees.")).toBeVisible();
  await expect(card.getByText(/0\.812/)).toBeVisible();
  await expect(card.getByText(/embed 12 ms \/ search 8 ms \/ rewrite 30 ms/)).toBeVisible();
  await expect(card.getByText("monthly instalment due")).toBeVisible();
  await expect(page.locator("#turn-0").getByTestId("retrieval-card")).toHaveCount(0);
  await expect(page.getByTestId("retrieval-card")).toHaveCount(1);
});
