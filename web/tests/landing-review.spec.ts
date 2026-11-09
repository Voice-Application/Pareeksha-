import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * The redesigned landing leads with the product's job and a single call to action, and shares the
 * app's design tokens (no separate marketing palette). It no longer embeds the interactive
 * run-replay widget, so this spec checks the hero, the primary CTA, the "How it works" section,
 * the product visual's accessible name, and that the page is accessible.
 */
test("landing leads with the job and sends you to the test page", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/welcome");

  // Hero states the value proposition as the single level-1 heading.
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Find the bugs in your bot");

  // Every primary CTA points at the one-screen prompt test.
  const ctas = page.getByRole("link", { name: "Test my prompt" });
  await expect(ctas.first()).toBeVisible();
  for (const cta of await ctas.all()) {
    await expect(cta).toHaveAttribute("href", "/test");
  }

  // The "How it works" section is reachable from the in-page anchor.
  await expect(page.getByRole("heading", { name: /How it works/i })).toBeVisible();

  // The product visual (the demo score meter) carries a descriptive accessible name, not a decorative placeholder.
  await expect(page.getByRole("img").first()).toHaveAccessibleName(/score/i);

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
