import { test, expect } from "@playwright/test";

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
