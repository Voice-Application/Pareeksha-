import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * The landing leads with the product's job and one call to action, and shares the app's design
 * tokens (no separate marketing palette). This spec checks the hero (including the Kannada caller
 * line), the CTAs, the "How it works" section, the demo's accessible names, and that the page is
 * accessible.
 */
test("landing leads with the job and sends you to the test page", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/welcome");

  // Hero states the value proposition as the single level-1 heading.
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Find the bugs in your bot");

  // The dialect story is above the fold: a caller line in Kannada script, marked with its language.
  await expect(page.locator('.lp-hero [lang="kn"]')).toBeVisible();

  // Every primary CTA points at the one-screen prompt test: nav, hero and the closing CTA only.
  const ctas = page.getByRole("link", { name: "Test my prompt" });
  await expect(ctas.first()).toBeVisible();
  await expect(ctas).toHaveCount(3);
  for (const cta of await ctas.all()) {
    await expect(cta).toHaveAttribute("href", "/test");
  }

  // The "How it works" section is reachable from the in-page anchor.
  await expect(page.getByRole("heading", { name: /How it works/i })).toBeVisible();
  await expect(page.locator("#how")).toBeAttached();

  // The middle of the page shows the bot's own wrong answers, not a feature grid.
  await expect(page.getByRole("heading", { name: "What it catches" })).toBeVisible();

  // The product visual (the demo score meter) carries a descriptive accessible name, not a decorative placeholder.
  await expect(page.getByRole("img").first()).toHaveAccessibleName(/score/i);

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test("sample-output tabs are reachable with the arrow keys", async ({ page }) => {
  await page.goto("/welcome");
  const first = page.getByRole("tab", { name: "Judged transcript" });
  await first.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Dialect gaps" })).toBeFocused();
  await expect(page.getByRole("tab", { name: "Dialect gaps" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "RAG compare" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(first).toBeFocused();
});

test("the flagged transcript turn says it broke a rule", async ({ page }) => {
  await page.goto("/welcome");
  await expect(page.getByRole("tabpanel").getByRole("button", { name: /Broke a rule/ })).toHaveCount(1);
});
