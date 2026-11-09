import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mockFe, opsState, run, RUN_ID, CALL_ID } from "./support/fe03-mock";

async function axeClean(page: import("@playwright/test").Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.nodes[0]?.target} ${v.nodes[0]?.html?.slice(0, 160)}`)).toEqual([]);
}

test.describe("runs list", () => {
  test("lists runs with pass rate, suite verdict and progress; compare needs two", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto("/runs");
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
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

  test("failure type rows retain a visible bar with a long label", async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    const st = opsState();
    const tag = "failure_".repeat(30);
    const base = run();
    st.extra[`GET /runs/${RUN_ID}`] = run({ summary: { ...base.summary, top_failure_types: [[tag, 2]] } });
    await mockFe(page, st);
    await page.goto(`/runs/${RUN_ID}`);
    const row = page.getByText(tag, { exact: true }).locator("../..");
    const label = row.locator(":scope > span").nth(0);
    const bar = row.locator(":scope > span").nth(1);
    await expect(label).toBeVisible();
    const sizes = await row.evaluate((el) => ({ row: el.clientWidth, label: el.children[0].getBoundingClientRect().width, bar: el.children[1].getBoundingClientRect().width }));
    expect(sizes.bar).toBeGreaterThanOrEqual(32);
    expect(sizes.label + sizes.bar).toBeLessThan(sizes.row);
    await expect(bar.locator("span")).toHaveCSS("width", `${sizes.bar}px`);
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
  test("recent runs wrap long unbroken names within the table", async ({ page }) => {
    await page.setViewportSize({ width: 1000, height: 800 });
    const st = opsState();
    const name = "long_run_name".repeat(30);
    st.extra["GET /runs"] = { items: [run({ name })], next_cursor: null };
    await mockFe(page, st);
    await page.goto("/");
    // exact: the trend chart's screen-reader table is "Mean score across recent runs".
    const table = page.getByRole("table", { name: "Recent runs", exact: true });
    const link = table.getByRole("link", { name });
    await expect(link).toHaveAttribute("href", `/runs/${RUN_ID}`);
    const size = await table.evaluate((el) => ({ table: el.getBoundingClientRect().width, container: el.parentElement!.getBoundingClientRect().width }));
    expect(size.table).toBeLessThanOrEqual(size.container + 1);
  });

  test("a refresh to fewer runs while a chart point is selected does not crash the charts", async ({ page }) => {
    const st = opsState();
    const scored = (i: number, pass: number) => run({ id: `00000000-0000-4000-8000-00000000091${i}`, name: `Run ${i}`, summary: { ...run().summary, pass_rate: pass, score_mean: 60 + i } });
    st.extra["GET /runs"] = { items: [scored(1, 0.5), scored(2, 0.75), scored(3, 0.999)], next_cursor: null };
    await mockFe(page, st);
    await page.goto("/");
    const passPanel = page.getByRole("region", { name: "Pass rate by run" });
    // 999/1000 must not read as a perfect run.
    await expect(passPanel.getByRole("button", { name: "Run 3: 99.9%" })).toBeVisible();
    await passPanel.getByRole("button", { name: /^Run 1: / }).focus();
    await expect(page.getByRole("tooltip")).toBeVisible();
    // Escape dismisses the tooltip without moving focus off the bar.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await expect(passPanel.getByRole("button", { name: /^Run 1: / })).toBeFocused();
    // Select the last bar, then let the overview refetch a single run: the stale index must not throw.
    st.extra["GET /runs"] = { items: [scored(9, 0.5)], next_cursor: null };
    await passPanel.getByRole("button", { name: "Run 3: 99.9%" }).focus();
    await page.waitForTimeout(5_200); // past the 5s staleTime, so the focus refetch (focusManager listens on window) runs
    await page.evaluate(() => window.dispatchEvent(new Event("visibilitychange")));
    await expect(passPanel.getByRole("button", { name: /^Run 9: / })).toBeVisible();
    await expect(page.getByRole("region", { name: "Mean score by run" })).toBeVisible();
  });

  test("the token chart is project-wide, counts scenario generation, and shows a retry when usage fails", async ({ page }) => {
    const st = opsState();
    st.extra["GET /runs"] = { items: [run({ summary: {} })], next_cursor: null };
    st.extra["GET /usage"] = { items: [{ provider: "openai", operation: "llm_scenario_gen", unit_type: "tokens", units: 1200 }], credits_used: 1, budget_credits: null, remaining_budget: null };
    await mockFe(page, st);
    await page.goto("/");
    const tokens = page.getByRole("region", { name: "Token usage by operation, all agents" });
    // Scenario-generation tokens are counted (grouped as "Other"), not dropped.
    await expect(tokens.getByRole("listitem").filter({ hasText: "Other" })).toContainText("100%");
    await expect(tokens.getByRole("cell", { name: "1200" })).toBeAttached();

    const failing = opsState();
    failing.extra["GET /runs"] = { items: [run({ summary: {} })], next_cursor: null };
    failing.fail["GET /usage"] = 500;
    await page.unrouteAll();
    await mockFe(page, failing);
    await page.reload();
    const errored = page.getByRole("region", { name: "Token usage by operation, all agents" });
    await expect(errored.getByRole("button", { name: "Retry" })).toBeVisible({ timeout: 10_000 });
  });

  test("title from the latest run, tiles link, health and review panels", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto("/");
    // The home now leads with prompt tests; the latest-run summary is the monitoring section heading below.
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Your prompt tests");
    await expect(page.getByRole("heading", { level: 2, name: /Latest run passed/ })).toBeVisible();
    // Ops telemetry sits in its own admin section, not in the run summary.
    const platform = page.getByRole("region", { name: "Platform (admins only)" });
    await expect(platform.getByRole("link", { name: /Open DLQ items/ })).toHaveAttribute("href", "/dlq");
    await expect(platform.getByRole("heading", { name: "Platform health", exact: true })).toBeVisible();
    await expect(platform.getByText("Lag:").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Needs human review" })).toBeVisible();
    await axeClean(page);
  });
});

