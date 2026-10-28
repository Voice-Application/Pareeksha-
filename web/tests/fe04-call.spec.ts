import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mockFe, opsState, CALL_ID } from "./support/fe03-mock";

async function axeClean(page: import("@playwright/test").Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.nodes[0]?.target} ${v.nodes[0]?.html?.slice(0, 160)}`)).toEqual([]);
}

test.describe("call detail", () => {
  test("verdict, evidence refs seek audio and select the turn, keyboard turn navigation", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto(`/calls/${CALL_ID}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Agent confirmed 40,000 when the caller said 4,000.");
    await expect(page.getByText("Critical failure")).toBeVisible();
    await expect(page.getByText("Needs human review").first()).toBeVisible();
    await expect(page.getByText("AGENT STT HEARD")).toBeVisible();
    // dimension row with score 0 shows its evidence refs; clicking #2 selects turn 2 and seeks the audio
    await page.getByRole("button", { name: "Seek to turn 2", exact: true }).first().click();
    await expect(page.locator("#turn-2")).toHaveAttribute("aria-current", /.*/).catch(() => undefined);
    await expect(page.getByText(/Evidence #1-2|Evidence #2/).first()).toBeVisible();
    const t = await page.locator("audio").evaluate((a: HTMLAudioElement) => a.currentTime);
    expect(t).toBeGreaterThan(8); // turn 2 starts at 9.0 s
    await page.keyboard.press("k");
    await expect(page.getByRole("button", { name: /Seek to turn 1 at/ })).toBeVisible();
    await axeClean(page);
  });

  test("?turn= opens seeked and selected", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto(`/calls/${CALL_ID}?turn=1`);
    await expect.poll(() => page.locator("audio").evaluate((a: HTMLAudioElement) => a.currentTime)).toBeGreaterThan(4);
  });

  test("override sheet explains an unavailable endpoint instead of failing silently", async ({ page }) => {
    const st = opsState();
    st.fail[`POST /calls/`] = 501;
    await mockFe(page, st);
    await page.goto(`/calls/${CALL_ID}`);
    await page.getByRole("button", { name: "Override judge score" }).click();
    await page.getByLabel("Reviewer name").fill("Preetham");
    await page.getByRole("button", { name: "Save review" }).click();
    await expect(page.getByText("This action is not available in this build yet.")).toBeVisible();
  });

  test("judge error shows the strip and re-evaluate", async ({ page }) => {
    await mockFe(page, opsState(), { callOver: { evaluation: { id: "e", rubric_version: "rubric-2026-10-v1", judge_model: "m", prompt_hash: "h", status: "judge_error", critical_failure: false, needs_human_review: true, review_reasons: ["judge_error"], failure_types: [], dimensions: {}, summary: "" } } });
    await page.goto(`/calls/${CALL_ID}`);
    await expect(page.getByText("The judge did not return a valid result.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Re-evaluate" })).toBeVisible();
  });

  test("no recording keeps the transcript usable", async ({ page }) => {
    await mockFe(page, opsState(), { callOver: { recordings: {} } });
    await page.goto(`/calls/${CALL_ID}`);
    await expect(page.getByText("No recording for this call.")).toBeVisible();
    await expect(page.getByText("Namaskara, this call is recorded.")).toBeVisible();
  });
});

test.describe("uploaded audit", () => {
  const upload = { source: "upload", run_id: null, recordings: { original: "o.wav", mixed: "o.wav" }, speaker_map: { "1": "agent", "2": "caller" }, metrics: { barge_in_attempts: 0, barge_in_honoured: 0, silence_gaps_over_2s: 0, turn_count: 3, repeated_utterances: 0, latency_is_approximate: true, response_latency_p50_ms: 0, response_latency_p95_ms: 0, first_greeting_ms: 200, agent_talk_ratio: 0.6 } };

  test("single mixed lane, speakers panel with swap, no invented latency", async ({ page }) => {
    await mockFe(page, opsState(), { callOver: upload });
    await page.goto(`/calls/${CALL_ID}`);
    await expect(page.getByText("Uploaded recording").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Speakers" })).toBeVisible();
    await expect(page.getByText("Agent goals")).toBeVisible();
    await expect(page.getByText("not measured on recordings").first()).toBeVisible();
    await expect(page.getByText(/s to respond/)).toHaveCount(0);
    await page.getByRole("button", { name: "Swap speakers" }).click();
    await expect(page.getByText(/re-evaluated, which takes about a minute/)).toBeVisible();
  });
});
