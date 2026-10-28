import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { agent, uuid } from "./support/mock-api";
import { callDetail, run } from "./support/fe03-mock";

const BASE = uuid(1000);
const HEAD = uuid(1001);
const OTHER = uuid(1002);

async function axeClean(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.nodes[0]?.target} ${v.nodes[0]?.html?.slice(0, 160)}`)).toEqual([]);
}

const cell = (scenario: string, persona: string, base: number | null, head: number | null, newly = false) => ({
  scenario, persona, profile: "clean_16k", base_score: base, head_score: head, delta: base != null && head != null ? head - base : null, newly_failing: newly,
});
const CELLS = [cell("Already paid", "Manju", 86, 52, true), cell("Promise to pay", "Manju", 71, 60), cell("Already paid", "Sunita", 70, 92), cell("Promise to pay", "Sunita", 90, 90)];

const item = (n: number, runBase: number, c: ReturnType<typeof cell>, score: number | null) => ({
  id: uuid(runBase + n), scenario: c.scenario, persona: c.persona, noise_profile: c.profile, status: "evaluated", call_id: uuid(runBase + 50 + n), overall_score: score, passed: score != null && score >= 80, critical_failure: false,
});

type St = { fail: Record<string, number>; cells: ReturnType<typeof cell>[]; headStatus: string; headAgent: string };
const newSt = (): St => ({ fail: {}, cells: CELLS, headStatus: "completed", headAgent: agent(1).id });

async function mockCompare(page: Page, st: St) {
  await page.route(/\/api\/proxy\/api\/v1\//, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/proxy/api/v1", "");
    const send = (json: unknown, status = 200) => route.fulfill({ status, json, headers: { "x-request-id": "req_test_0002" } });
    const forced = Object.entries(st.fail).find(([k]) => path.startsWith(k));
    if (forced) return send({ error: { code: forced[1] === 404 ? "not_found" : "internal", message: forced[1] === 404 ? "Run not found" : "Forced failure." } }, forced[1]);
    const runs = {
      [BASE]: run({ id: BASE, name: "Prompt v2", summary: { pass_rate: 0.75, critical_failures: 0, needs_review: 0, score_mean: 79.2, latency_p50_ms: 900, latency_p95_ms: 1800, top_failure_types: [], score_distribution: [] } }),
      [HEAD]: run({ id: HEAD, name: "Prompt v3", status: st.headStatus, agent_id: st.headAgent, created_at: "2026-10-26T10:00:00Z", summary: { pass_rate: 0.5, critical_failures: 1, needs_review: 1, score_mean: 73.5, latency_p50_ms: 1000, latency_p95_ms: 2400, top_failure_types: [], score_distribution: [] } }),
      [OTHER]: run({ id: OTHER, name: "Other agent run", agent_id: agent(2).id }),
    } as Record<string, ReturnType<typeof run>>;
    if (path === "/runs") return send({ items: Object.values(runs), next_cursor: null });
    if (path === "/runs/compare") {
      const cells = st.cells;
      return send({ cells, summary: { regressed: cells.filter((c) => (c.delta ?? 0) < 0).length, improved: cells.filter((c) => (c.delta ?? 0) > 0).length, unchanged: cells.filter((c) => c.delta === 0).length } });
    }
    const m = path.match(/^\/runs\/([^/]+)(\/items)?$/);
    if (m && m[2]) return send({ items: CELLS.map((c, i) => item(i, m[1] === BASE ? 100 : 200, c, m[1] === BASE ? c.base_score : c.head_score)), next_cursor: null });
    if (m) return runs[m[1]] ? send(runs[m[1]]) : send({ error: { code: "not_found", message: "Run not found" } }, 404);
    if (/^\/agents\/[^/]+$/.test(path)) {
      const id = path.split("/")[2];
      return send(id === agent(2).id ? { ...agent(2), name: "Collections Bot", description: "Handles late-stage collections.", forbidden_phrases: [{ id: "f1", text: "threaten arrest" }] } : agent(1));
    }
    const c = path.match(/^\/calls\/([^/]+)$/);
    if (c) {
      const isHead = Number(c[1].slice(-3)) >= 250;
      const base = callDetail().evaluation;
      const dims = Object.fromEntries(Object.entries(base.dimensions).map(([k, v]) => [k, { ...v, score: isHead && k === "factual_accuracy" ? 0 : 3 }]));
      return send(callDetail({ id: c[1], evaluation: { ...base, dimensions: dims } }));
    }
    return send({ items: [], next_cursor: null });
  });
}

test.describe("run compare", () => {
  test("missing parameters: choose two runs, then compare", async ({ page }) => {
    await mockCompare(page, newSt());
    await page.goto("/runs/compare");
    await expect(page.getByRole("heading", { level: 1, name: "Choose two runs to compare" })).toBeVisible();
    const compare = page.getByRole("button", { name: "Compare" });
    await expect(compare).toBeDisabled();
    await page.getByLabel("Base run").selectOption(BASE);
    await expect(compare).toBeDisabled();
    await page.getByLabel("Head run").selectOption(HEAD);
    await expect(compare).toBeEnabled();
    await axeClean(page);
    await compare.click();
    await expect(page).toHaveURL(new RegExp(`base=${BASE}&head=${HEAD}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText("2 cells regressed, 1 improved, 1 unchanged");
  });

  test("summary, regressions first, deltas in words, call links; axe in light and dark", async ({ page }) => {
    await mockCompare(page, newSt());
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(`/runs/compare?base=${BASE}&head=${HEAD}`);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("2 cells regressed, 1 improved, 1 unchanged");
      await expect(page.getByText("Pass rate 75% to 50%.")).toBeVisible();
      await expect(page.getByText(/Newly failing: Already paid x Manju \(86 to 52\)/)).toBeVisible();
      const tiles = page.locator("dl > div");
      await expect(tiles.filter({ hasText: "Pass rate" })).toContainText("down 25 points, worse");
      await expect(tiles.filter({ hasText: "Critical" })).toContainText("up 1 failure, worse");
      await expect(tiles.filter({ hasText: "Latency p95" })).toContainText("up 0.6 s, worse");
      const rows = page.getByRole("table", { name: "Changed cells, regressions first" }).getByRole("row");
      await expect(rows).toHaveCount(4);
      await expect(rows.nth(1)).toContainText("Already paid");
      await expect(rows.nth(1)).toContainText("newly failing");
      await expect(rows.nth(1)).toContainText("-34.0");
      await expect(rows.nth(2)).toContainText("regressed");
      await expect(rows.nth(3)).toContainText("improved");
      await expect(rows.nth(1).getByRole("link", { name: "Base call" })).toHaveAttribute("href", /\/calls\//);
      await expect(rows.nth(1).getByRole("link", { name: "Head call" })).toHaveAttribute("href", /\/calls\//);
      await expect(page.locator("details", { hasText: "1 unchanged" })).not.toHaveAttribute("open", "");
      const dim = page.getByRole("table", { name: "Mean dimension score per run" });
      await expect(dim.getByRole("row", { name: /Factual accuracy/ })).toContainText("-3.00");
      await expect(page.getByText("Both runs used the same agent.")).toBeVisible();
      await axeClean(page);
    }
  });

  test("diff heatmap: head score, signed delta, arrow keys, outline on newly failing", async ({ page }) => {
    await mockCompare(page, newSt());
    await page.goto(`/runs/compare?base=${BASE}&head=${HEAD}`);
    const grid = page.getByRole("grid", { name: /Diff matrix/ });
    const first = grid.getByRole("gridcell").first();
    await expect(first).toHaveAttribute("aria-label", /head 52, -34.0 from base, newly failing/);
    await expect(first).toContainText("-34");
    await first.focus();
    await page.keyboard.press("ArrowRight");
    await expect(grid.getByRole("gridcell").nth(1)).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(grid.getByRole("gridcell").nth(3)).toBeFocused();
    await expect(grid.getByRole("gridcell").nth(3)).toHaveAttribute("aria-label", /unchanged/);
  });

  test("swap and pickers update the URL", async ({ page }) => {
    await mockCompare(page, newSt());
    await page.goto(`/runs/compare?base=${BASE}&head=${HEAD}`);
    await page.getByRole("button", { name: "Swap base and head" }).click();
    await expect(page).toHaveURL(new RegExp(`base=${HEAD}&head=${BASE}`));
    await page.getByLabel("Head run").selectOption(OTHER);
    await expect(page).toHaveURL(new RegExp(`head=${OTHER}`));
    await expect(page.getByText("These runs used different agents.")).toBeVisible();
  });

  test("different agents: strip and agent diff", async ({ page }) => {
    const st = newSt();
    st.headAgent = agent(2).id;
    await mockCompare(page, st);
    await page.goto(`/runs/compare?base=${BASE}&head=${HEAD}`);
    await expect(page.getByText("These runs used different agents. Differences may not come from a prompt change.")).toBeVisible();
    const panel = page.getByRole("region", { name: "What changed in the agent" });
    await expect(panel).toContainText("threaten arrest");
    await expect(panel.getByRole("img", { name: "added" }).first()).toBeVisible();
    await expect(panel.getByRole("img", { name: "removed" }).first()).toBeVisible();
    await axeClean(page);
  });

  test("same run twice", async ({ page }) => {
    await mockCompare(page, newSt());
    await page.goto(`/runs/compare?base=${BASE}&head=${BASE}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Base and head are the same run");
    await expect(page.getByRole("status").filter({ hasText: "Choose two different runs" })).toBeVisible();
  });

  test("head still running shows the banner", async ({ page }) => {
    const st = newSt();
    st.headStatus = "running";
    await mockCompare(page, st);
    await page.goto(`/runs/compare?base=${BASE}&head=${HEAD}`);
    await expect(page.getByText("Head is still running. Results update when it finishes.")).toBeVisible();
  });

  test("no overlapping cells and no differences", async ({ page }) => {
    const st = newSt();
    st.cells = [cell("Already paid", "Manju", 80, null), cell("Promise to pay", "Manju", null, 70)];
    await mockCompare(page, st);
    await page.goto(`/runs/compare?base=${BASE}&head=${HEAD}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("No overlapping cells");
    await expect(page.getByText("These runs share no scenario, persona and line combination")).toBeVisible();
    await axeClean(page);

    st.cells = [cell("Already paid", "Manju", 80, 80), cell("Promise to pay", "Manju", 70, 70)];
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("No differences");
    await expect(page.getByText("No cell changed score between these runs.")).toBeVisible();
  });

  test("compare failure keeps the tiles and offers retry; missing run names the error", async ({ page }) => {
    const st = newSt();
    st.fail["/runs/compare"] = 500;
    await mockCompare(page, st);
    await page.goto(`/runs/compare?base=${BASE}&head=${HEAD}`);
    await expect(page.getByRole("alert").filter({ hasText: "Could not load the comparison" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    await expect(page.locator("dl > div").filter({ hasText: "Pass rate" })).toContainText("down 25 points");
    delete st.fail["/runs/compare"];
    await page.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("2 cells regressed");

    await page.goto(`/runs/compare?base=${uuid(9999)}&head=${HEAD}`);
    await expect(page.getByRole("alert").filter({ hasText: "Run not found" })).toBeVisible();
  });

  test("loading state shows skeletons", async ({ page }) => {
    await mockCompare(page, newSt());
    await page.route(/\/runs\/compare/, async (r) => { await new Promise((x) => setTimeout(x, 800)); await r.fallback(); });
    await page.goto(`/runs/compare?base=${BASE}&head=${HEAD}`);
    await expect(page.getByRole("status", { name: "Loading comparison" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("2 cells regressed");
  });
});
