import { test, expect } from "@playwright/test";
import { mockFe, opsState, run } from "./support/fe03-mock";

const usage = (operations: [string, number][]) => ({
  items: operations.map(([operation, units]) => ({ provider: "synthetic", operation, units, unit_type: "tokens" })),
  credits_used: 1,
});

test("project token colors survive filtering and narrow slices support pointer and Escape", async ({ page }) => {
  const state = opsState();
  state.extra["GET /usage"] = usage([["llm_caller", 1], ["llm_designer", 1000], ["llm_judge", 1000], ["llm_scenario_gen", 1000]]);
  await mockFe(page, state);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const panel = page.getByRole("region", { name: "Project token usage by operation" });
  const marks = panel.locator('svg g[role="button"]');
  await expect(marks).toHaveCount(4);
  const colors = await marks.locator("path:first-child").evaluateAll((paths) => paths.map((p) => p.getAttribute("fill")));
  expect(new Set(colors).size).toBe(4);
  const swatches = await panel.locator("li span[aria-hidden]").evaluateAll((spans) => spans.map((s) => (s as HTMLElement).style.background));
  expect(swatches).toEqual(colors);
  const narrow = marks.first();
  expect(await narrow.locator("path").first().getAttribute("d")).not.toContain("NaN");
  await panel.locator("svg > circle").hover();
  await expect(panel.getByRole("tooltip")).toContainText("Caller");
  await narrow.focus();
  await page.keyboard.press("Escape");
  await expect(panel.getByRole("tooltip")).toHaveCount(0);
  await expect(narrow).toBeFocused();
  state.extra["GET /usage"] = usage([["llm_judge", 7]]);
  await page.reload();
  await expect(marks).toHaveCount(1);
  await expect(marks.locator("path").first()).toHaveAttribute("fill", colors[2]!);
  state.extra["GET /usage"] = usage([["llm_scenario_gen", 123]]);
  await page.reload();
  await expect(panel.getByRole("table")).toContainText("123");
});

test("pass-rate chart and table retain near-perfect precision", async ({ page }) => {
  const state = opsState();
  state.extra["GET /runs"] = { items: [run({ summary: { pass_rate: 0.999, score_mean: 95 } })] };
  await mockFe(page, state);
  await page.goto("/");
  const panel = page.getByRole("region", { name: "Pass rate by run" });
  await expect(panel.getByRole("button", { name: /99.9%/ })).toBeVisible();
  await expect(panel.getByRole("table")).toContainText("99.9");
});

test("usage failure without scored runs offers retry; empty success hides charts", async ({ page }) => {
  const state = opsState();
  state.extra["GET /runs"] = { items: [] };
  state.fail["GET /usage"] = 500;
  await mockFe(page, state);
  await page.goto("/");
  const panel = page.getByRole("region", { name: "Project token usage by operation" });
  await expect(panel.getByRole("alert")).toContainText("Could not load token usage");
  delete state.fail["GET /usage"];
  await panel.getByRole("button", { name: "Retry" }).click();
  await expect(panel).toHaveCount(0);
});

test("line pointer uses plot bounds and Escape retains plot focus", async ({ page }) => {
  const state = opsState();
  state.extra["GET /runs"] = { items: [
    run({ id: "new", name: "Newest" }),
    run({ id: "mid", name: "Middle" }),
    run({ id: "old", name: "Oldest" }),
  ] };
  await mockFe(page, state);
  await page.goto("/");
  const panel = page.getByRole("region", { name: "Mean score by run" });
  const plot = panel.getByRole("slider");
  await plot.scrollIntoViewIfNeeded();
  const box = (await plot.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.26, box.y + box.height / 2);
  await expect(panel.getByRole("tooltip")).toContainText("Middle");
  await plot.focus();
  await page.keyboard.press("Escape");
  await expect(panel.getByRole("tooltip")).toHaveCount(0);
  await expect(plot).toBeFocused();
});
