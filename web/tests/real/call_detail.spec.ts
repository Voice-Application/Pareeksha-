import { test, expect } from "@playwright/test";
import { api, firstEvaluatedCall } from "./support";

// FR-DB-3: clicking an evidence reference seeks the audio.
test("evidence turn click seeks the real recording", async ({ page }) => {
  const { callId } = await firstEvaluatedCall();
  const call = await api<{ turns: { idx: number; start_ms: number }[] }>(`/calls/${callId}`);
  await page.goto(`/calls/${callId}`);
  await expect(page.locator("audio")).toHaveCount(1);
  const turn = call.turns.find((t) => t.idx >= 1);
  if (!turn) throw new Error("call has no turn after the first");
  await page.getByRole("button", { name: new RegExp(`^Seek to turn ${turn.idx}( at|$)`) }).first().click();
  await expect
    .poll(() => page.locator("audio").evaluate((a: HTMLAudioElement) => a.currentTime))
    .toBeGreaterThanOrEqual(Math.max(0, turn.start_ms / 1000 - 1));
});
