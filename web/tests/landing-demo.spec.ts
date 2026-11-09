import { test, expect } from "@playwright/test";

test("reduced motion shows a finished demo and prevents replay", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/welcome");
  const demo = page.locator(".lp-demo");
  await expect(demo).toBeVisible();
  await expect(demo.getByRole("button", { name: "Replay" })).toBeDisabled();
  await expect(demo.locator(".lp-demo__verdict")).toHaveAttribute("aria-hidden", "false");
  await expect(demo.locator('.lp-demo__turn[aria-hidden="true"]')).toHaveCount(0);
});

test("demo exposes turns at their beats and preserves pause and replay", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.clock.install();
  await page.goto("/welcome");
  const demo = page.locator(".lp-demo");
  await expect(demo.getByRole("button", { name: "Pause" })).toBeVisible();
  const turns = demo.locator(".lp-demo__turn");
  await expect(turns.nth(0)).toHaveAttribute("aria-hidden", "true");
  await expect(turns.nth(1)).toHaveAttribute("aria-hidden", "true");
  expect(await turns.first().evaluate((el) => getComputedStyle(el).transitionDuration)).toBe("0s");
  await page.clock.fastForward(1400);
  await expect(turns.nth(0)).toHaveAttribute("aria-hidden", "false");
  await expect(turns.nth(1)).toHaveAttribute("aria-hidden", "true");
  await demo.getByRole("button", { name: "Pause" }).click();
  await page.clock.fastForward(2800);
  await expect(turns.nth(1)).toHaveAttribute("aria-hidden", "true");
  await demo.getByRole("button", { name: "Play", exact: true }).click();
  await page.clock.fastForward(1400);
  await expect(turns.nth(1)).toHaveAttribute("aria-hidden", "false");
  await page.clock.fastForward(1400);
  await demo.getByRole("button", { name: "Replay" }).click();
  expect(await turns.first().evaluate((el) => getComputedStyle(el).transitionDuration)).not.toBe("0s");
  await expect(turns.nth(0)).toHaveAttribute("aria-hidden", "true");
  await page.clock.fastForward(1400);
  await expect(turns.nth(0)).toHaveAttribute("aria-hidden", "false");
});

test("tabs support arrow navigation, wraparound and keyboard activation", async ({ page }) => {
  await page.goto("/welcome");
  const tabs = page.getByRole("tab");
  await tabs.nth(0).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(tabs.nth(2)).toBeFocused();
  await expect(tabs.nth(2)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight");
  await expect(tabs.nth(0)).toBeFocused();
  for (const index of [1, 2]) {
    await page.keyboard.press("ArrowRight");
    await expect(tabs.nth(index)).toBeFocused();
    await expect(tabs.nth(index)).toHaveAttribute("tabindex", "0");
    await page.keyboard.press(index === 1 ? "Enter" : "Space");
    await expect(tabs.nth(index)).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", await tabs.nth(index).getAttribute("id") as string);
  }
  await page.keyboard.press("Home");
  await expect(tabs.nth(0)).toBeFocused();
  await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("End");
  await expect(tabs.nth(2)).toBeFocused();
  await expect(tabs.nth(2)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Tab");
  await expect(tabs.nth(2)).not.toBeFocused();
});
