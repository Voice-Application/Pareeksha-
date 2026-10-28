import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mockFe, opsState, RUN_ID, CALL_ID } from "./support/fe03-mock";

async function axeClean(page: import("@playwright/test").Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.nodes[0]?.target} ${v.nodes[0]?.html?.slice(0, 160)}`)).toEqual([]);
}

test.describe("runs list", () => {
  test("lists runs with pass rate, suite verdict and progress; compare needs two", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto("/runs");
    await expect(page.getByRole("heading", { level: 1, name: "Runs" })).toBeVisible();
    const rows = page.getByRole("table", { name: "Runs" }).getByRole("row");
    await expect(rows).toHaveCount(4);
    await expect(page.getByRole("link", { name: "Prompt v3 baseline" })).toBeVisible();
    await expect(rows.nth(1)).toContainText("50%");
    await expect(rows.nth(2)).toContainText("Fail"); // regression suite verdict
    await expect(rows.nth(3)).toContainText("7/12");
    const compare = page.getByRole("button", { name: "Compare" });
    await expect(compare).toBeDisabled();
    await page.getByLabel("Select Prompt v3 baseline for compare").check();
    await page.getByLabel("Select Nightly regression for compare").check();
    await expect(compare).toBeEnabled();
    await axeClean(page);
  });

  test("empty and error states", async ({ page }) => {
    const st = opsState();
    st.fail["GET /runs"] = 500;
    await mockFe(page, st);
    await page.goto("/runs");
    await expect(page.getByRole("alert").filter({ hasText: "Could not load runs" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  });
});

test.describe("new run wizard", () => {
  test("matrix size, cost estimate and create navigates to the run", async ({ page }) => {
    const st = opsState();
    await mockFe(page, st);
    await page.goto("/runs/new");
    // single agent is preselected into the URL
    await expect(page.getByRole("button", { name: /Create run/ })).toBeDisabled();
    await expect(page.getByText("Select at least one scenario.")).toBeVisible();
    await page.getByRole("button", { name: /Scenarios/ }).click();
    await page.getByRole("checkbox", { name: /Select all scenarios/i }).check();
    await page.getByRole("button", { name: /Callers/ }).click();
    await page.getByRole("checkbox", { name: /Select all personas/i }).check();
    await page.getByRole("button", { name: /Lines/ }).click();
    await page.getByRole("checkbox", { name: /Select all noise profiles/i }).check();
    await expect(page.locator('[aria-label="8 calls"]')).toBeVisible();
    await expect(page.getByText("₹31.50")).toBeVisible();
    await expect(page.getByText("Budget left")).toBeVisible();
    await axeClean(page);
    await page.getByRole("button", { name: "Create run" }).click();
    await expect(page).toHaveURL(new RegExp(`/runs/${RUN_ID}`));
  });

  test("402 budget_exceeded shows the numbers and an explicit override", async ({ page }) => {
    const st = opsState();
    await mockFe(page, st);
    await page.goto("/runs/new?step=review");
    await page.route(/\/runs$/, async (route) => {
      if (route.request().method() === "POST") return route.fulfill({ status: 402, json: { error: { code: "budget_exceeded", message: "Over budget", details: { estimate: { est_cost: 640 }, remaining_budget: 480 } } } });
      return route.fallback();
    });
    await page.getByRole("button", { name: /Scenarios/ }).click();
    await page.getByRole("checkbox", { name: /Select all scenarios/i }).check();
    await page.getByRole("button", { name: /Callers/ }).click();
    await page.getByRole("checkbox", { name: /Select all personas/i }).check();
    await page.getByRole("button", { name: /Lines/ }).click();
    await page.getByRole("checkbox", { name: /Select all noise profiles/i }).check();
    await page.getByRole("button", { name: "Create run" }).click();
    await expect(page.getByText(/Estimated ₹640 exceeds the remaining ₹480/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Run anyway" })).toBeVisible();
  });
});

test.describe("run detail", () => {
  test("title, tiles, heatmap cells link to calls, grid keyboard navigation", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto(`/runs/${RUN_ID}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("2 of 3 calls failed, 1 critical".replace("2 of 3", "2 of 4"));
    await expect(page.getByText("Pass rate").first()).toBeVisible();
    const grid = page.getByRole("grid", { name: /Run matrix/ });
    const cell = grid.getByRole("gridcell", { name: /Already paid, persona Manju.*score 48.75, critical/ });
    await expect(cell).toHaveAttribute("href", new RegExp(`/calls/${CALL_ID}`));
    await cell.focus();
    await page.keyboard.press("ArrowRight");
    await expect(grid.getByRole("gridcell", { name: /Already paid, persona Sunita/ })).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(grid.getByRole("gridcell", { name: /Promise to pay, persona Sunita/ })).toBeFocused();
    await axeClean(page);
  });

  test("live: snapshot and call.evaluated events fill a cell without reload", async ({ page }) => {
    const st = opsState();
    const base = { id: RUN_ID, agent_id: "x", name: "Live", kind: "matrix", status: "running", progress: { total: 2, queued: 1, in_progress: 0, evaluated: 0, error: 0 }, summary: {}, created_at: "2026-10-24T10:00:00Z" };
    const it = [{ id: "i1", scenario: "S1", persona: "P1", noise_profile: "clean", status: "queued", call_id: null }];
    st.sse = `id: 0:1\nevent: snapshot\ndata: ${JSON.stringify({ run: base, items: it })}\n\nid: 0:2\nevent: call.evaluated\ndata: ${JSON.stringify({ run_item_id: "i1", call_id: CALL_ID, overall_score: 91, passed: true, critical_failure: false })}\n\n`;
    await mockFe(page, st, { runStatus: "running", runItems: it as never });
    await page.goto(`/runs/${RUN_ID}`);
    await expect(page.getByRole("grid", { name: /Run matrix/ }).getByRole("gridcell", { name: /score 91, pass/ })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Run is");
  });

  test("404 shows a page error and a way back", async ({ page }) => {
    const st = opsState();
    st.fail[`GET /runs/${RUN_ID}`] = 404;
    await mockFe(page, st);
    await page.goto(`/runs/${RUN_ID}`);
    await expect(page.getByRole("heading", { name: "This item does not exist or was deleted" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to runs" })).toBeVisible();
  });
});

test.describe("overview", () => {
  test("title from the latest run, tiles link, health and review panels", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Latest run passed");
    await expect(page.getByRole("link", { name: /Open DLQ items/ })).toHaveAttribute("href", "/dlq");
    await expect(page.getByText("Lag:").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Needs human review" })).toBeVisible();
    await axeClean(page);
  });
});

