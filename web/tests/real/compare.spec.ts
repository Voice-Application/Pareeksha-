import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { api, watch } from "./support";

type R = { id: string; name: string; status: string; created_at: string };

// FE-03b: the compare page against two real finished runs (needs two completed runs of the same agent on the stack).
test("run compare renders two real runs: regressions, deltas, dimensions, no console errors", async ({ page }) => {
  const runs = (await api<{ items: R[] }>("/runs?limit=50")).items.filter((r) => r.status === "completed").sort((a, b) => a.created_at.localeCompare(b.created_at));
  expect(runs.length).toBeGreaterThanOrEqual(2);
  const base = runs[runs.length - 2];
  const head = runs[runs.length - 1];
  const server = await api<{ cells: { delta: number | null }[]; summary: { regressed: number; improved: number; unchanged: number } }>(`/runs/compare?base=${base.id}&head=${head.id}`);
  const problems = watch(page);
  await page.goto(`/runs/compare?base=${base.id}&head=${head.id}`);
  const s = server.summary;
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(s.regressed === 0 && s.improved === 0 ? "No differences" : `${s.regressed} cells regressed, ${s.improved} improved, ${s.unchanged} unchanged`);
  await expect(page.getByRole("table", { name: "Mean dimension score per run" }).getByRole("row")).toHaveCount(8);
  await expect(page.getByRole("grid", { name: /Diff matrix/ }).getByRole("gridcell").first()).toBeVisible();
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(r.violations.map((v) => v.id)).toEqual([]);
  expect(problems).toEqual([]);
});
