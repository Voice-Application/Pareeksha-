import { test, expect } from "@playwright/test";

test("copy feedback covers unavailable, rejected and successful clipboard writes", async ({ page }) => {
  await page.goto("/welcome");
  const button = page.getByRole("button", { name: "Copy command 1" });
  const result = page.locator(".lp-steps li").first().locator('[aria-live="polite"]');
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined }));
  await button.click();
  await expect(result).toHaveText("Select and copy");
  await expect(button).toHaveAccessibleName("Copy command 1");
  await expect(result).toHaveText("", { timeout: 3000 });
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.reject(new Error("denied")) } }));
  await button.click();
  await expect(result).toHaveText("Select and copy");
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.resolve() } }));
  await button.click();
  await expect(result).toHaveText("Copied");
  await expect(page.locator(".lp-steps li").nth(1).locator('[aria-live="polite"]')).toHaveText("");
});

test("pipeline pauses for focus and hover, and reduced motion retains selection", async ({ page }) => {
  await page.goto("/welcome");
  const pipe = page.locator(".lp-pipe");
  const first = pipe.locator("li").first();
  // The first stage's wire carries the progress animation; it must pause whenever the pipeline does.
  const playState = () => first.locator(".lp-stage__wire span").evaluate((el) => getComputedStyle(el).animationPlayState);
  await expect.poll(playState).toBe("paused");
  await pipe.scrollIntoViewIfNeeded();
  await page.mouse.move(0, 0);
  await expect(pipe).toHaveAttribute("data-running", "");
  await expect.poll(playState).toBe("running");
  await pipe.getByRole("button", { name: /Planner/ }).focus();
  await pipe.hover();
  await page.mouse.move(0, 0);
  await expect(pipe).not.toHaveAttribute("data-running", "");
  await expect.poll(playState).toBe("paused");
  await page.getByRole("heading", { name: "What happens on one call?" }).evaluate((el: HTMLElement) => { el.tabIndex = -1; el.focus(); });
  await expect(pipe).toHaveAttribute("data-running", "");
  await page.emulateMedia({ reducedMotion: "reduce" });
  const evaluator = pipe.getByRole("button", { name: /Evaluator/ });
  await evaluator.click();
  await expect(evaluator).toHaveAttribute("aria-pressed", "true");
  await expect(evaluator.locator(".." )).toHaveAttribute("data-active", "");
});

test("replay line selection, detail resets and failure labels", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/welcome");
  const replay = page.locator(".lp-rp");
  const phone = replay.getByRole("radio", { name: "Phone line" });
  const office = replay.getByRole("radio", { name: "Office babble" });
  await expect(phone).toHaveAttribute("tabindex", "0");
  await expect(office).toHaveAttribute("tabindex", "-1");
  await replay.getByRole("button", { name: /Asks for a human, Manju:/ }).focus();
  await expect(replay.locator(".lp-rp__detail")).toContainText("Manju");
  await phone.focus();
  await phone.press("ArrowRight");
  await expect(office).toBeFocused();
  await expect(office).toHaveAttribute("aria-checked", "true");
  await expect(replay.locator(".lp-rp__detail")).toContainText("Point at a score");
  await replay.getByRole("button", { name: /Asks for a human, Manju:/ }).focus();
  await replay.getByRole("button", { name: "Replay" }).click();
  await expect(replay.locator(".lp-rp__detail")).toContainText("Point at a score");
  await expect(replay.getByRole("button", { name: /not scored yet/ }).first()).toBeVisible();
  await page.reload();
  const tags = replay.getByRole("group", { name: "Highlight calls with this failure" });
  await tags.getByRole("button", { name: /wrong_fact/ }).click();
  await expect(replay.getByRole("button", { name: /Asks for a human, Manju:/ })).toHaveAccessibleName(/matches wrong_fact/);
  await expect(replay.getByRole("button", { name: /Asks for a human, Sunita:/ })).toHaveAccessibleName(/does not match wrong_fact/);
});
