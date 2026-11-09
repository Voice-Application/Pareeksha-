import { test, expect, type Locator } from "@playwright/test";

/** Background colour of `badge` and of a probe painted with the app's --critical token, resolved in the page. */
async function criticalColours(badge: Locator) {
  return badge.evaluate((el) => {
    const probe = document.createElement("span");
    probe.style.background = "var(--critical)";
    el.parentElement!.appendChild(probe);
    const want = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return { got: getComputedStyle(el).backgroundColor, want };
  });
}

test("reduced motion shows a finished demo and prevents replay", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/welcome");
  const demo = page.getByRole("region", { name: "A sample run, played out" });
  await expect(demo).toBeVisible();
  await expect(demo.getByRole("button", { name: "Replay" })).toBeDisabled();
  // Nothing is "revealed" under reduced motion, so the live region stays quiet.
  await expect(demo.locator(".lp-demo__live")).toHaveText("");
  // Critical is the only solid badge in the product; the demo uses the same one.
  const badge = demo.getByText("Critical failure");
  await expect(badge).toBeVisible();
  const { got, want } = await criticalColours(badge);
  expect(got).toBe(want);
  await expect(demo.locator(".lp-demo__verdict")).toHaveAttribute("aria-hidden", "false");
  await expect(demo.locator('.lp-demo__turn[aria-hidden="true"]')).toHaveCount(0);
});

test("demo exposes turns at their beats and preserves pause and replay", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.clock.install();
  await page.goto("/welcome");
  const demo = page.getByRole("region", { name: "A sample run, played out" });
  const live = demo.locator(".lp-demo__live");
  await expect(demo.getByRole("button", { name: "Pause" })).toBeVisible();
  // The label swaps between Pause and Play, so the button is not also a toggle.
  await expect(demo.getByRole("button", { name: "Pause" })).not.toHaveAttribute("aria-pressed", /.*/);
  // Only the hidden announcer is live; the visible list is not.
  await expect(demo.locator("[aria-live]")).toHaveCount(1);
  await expect(live).toHaveAttribute("aria-live", "polite");
  const turns = demo.locator(".lp-demo__turn");
  await expect(turns.nth(0)).toHaveAttribute("aria-hidden", "true");
  await expect(turns.nth(1)).toHaveAttribute("aria-hidden", "true");
  await page.clock.fastForward(1400);
  await expect(turns.nth(0)).toHaveAttribute("aria-hidden", "false");
  await expect(turns.nth(1)).toHaveAttribute("aria-hidden", "true");
  // The announcer holds only the line just revealed.
  await expect(live).toHaveText("Caller: Do you offer gold loans?");
  await demo.getByRole("button", { name: "Pause" }).click();
  await page.clock.fastForward(2800);
  await expect(turns.nth(1)).toHaveAttribute("aria-hidden", "true");
  await demo.getByRole("button", { name: "Play", exact: true }).click();
  await page.clock.fastForward(1400);
  await expect(turns.nth(1)).toHaveAttribute("aria-hidden", "false");
  await expect(live).toHaveText(/^Agent: Yes, we offer gold loans/);
  await page.clock.fastForward(1400);
  await expect(live).toHaveText(/^Critical failure\. Overall score 57\.5 of 100/);
  await demo.getByRole("button", { name: "Replay" }).click();
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
