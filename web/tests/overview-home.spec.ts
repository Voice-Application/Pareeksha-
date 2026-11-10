import { test, expect, type Page } from "@playwright/test";
import { mockFe, opsState, CALL_ID } from "./support/fe03-mock";
import { uuid } from "./support/mock-api";

// Home page behaviour from the design critique. The shared server (:3100) runs with sign-in disabled,
// so every visitor is an admin here; role splitting itself is covered by overview-role.spec.ts.

const quickTest = (n: number, status: "running" | "checking" | "done" | "failed") => ({
  id: uuid(1500 + n), name: `Support bot ${n}`, status, created_at: "2026-10-24T10:00:00Z", parent_id: null,
  rules_total: 6, rules_broken: status === "done" ? 1 : 0, rules_untested: 0, conversations: 4, finished: status === "done" ? 4 : 1,
});

/** The value cell next to a health row's label. */
const healthRow = (page: Page, label: string) =>
  page.getByRole("region", { name: "Platform health" }).locator("dt", { hasText: new RegExp(`^${label}$`) }).locator("xpath=following-sibling::dd[1]");

test.describe("overview home", () => {
  test("Get started shows until a prompt test has finished", async ({ page }) => {
    const st = opsState();
    await mockFe(page, st);
    await page.goto("/");
    await expect(page.getByRole("region", { name: "Get started" })).toBeVisible();

    // A test still running is not a finished one: the guide stays.
    st.extra["GET /quick-tests"] = [quickTest(1, "running")];
    await page.reload();
    await expect(page.getByRole("region", { name: "Prompt tests" }).getByRole("link", { name: "Support bot 1" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Get started" })).toBeVisible();

    st.extra["GET /quick-tests"] = [quickTest(2, "done"), quickTest(1, "failed")];
    await page.reload();
    const tests = page.getByRole("region", { name: "Prompt tests" });
    await expect(tests.getByRole("link", { name: "Support bot 2" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Get started" })).toHaveCount(0);
    // The aux link uses the same words as the rest of the app.
    await expect(tests.getByRole("link", { name: "Test my prompt", exact: true })).toHaveAttribute("href", "/test");
  });

  test("the API health row follows the health request, not the database", async ({ page }) => {
    const st = opsState();
    // A down dependency is reported with 503 and the same body.
    st.extra["GET /health"] = [503, { db: "down", kafka: "ok" }];
    await mockFe(page, st);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Platform (admins only)" })).toBeVisible();
    // The API answered, so it is ok even while the database is down.
    await expect(healthRow(page, "API")).toHaveText("ok");
    await expect(healthRow(page, "Database")).toHaveText("down");

    const failing = opsState();
    failing.fail["GET /health"] = 500;
    await page.unrouteAll();
    await mockFe(page, failing);
    await page.reload();
    // The query retries once before it reports the error.
    await expect(healthRow(page, "API")).toHaveText("unreachable", { timeout: 10_000 });
    await expect(healthRow(page, "Database")).toHaveText("unknown");
  });

  test("review links and the budget meter carry descriptive names", async ({ page }) => {
    await mockFe(page, opsState());
    await page.goto("/");
    const review = page.getByRole("region", { name: "Needs human review" });
    const link = review.getByRole("link", { name: `Review call ${CALL_ID.slice(0, 8)}, score 48.75` });
    await expect(link).toHaveAttribute("href", `/calls/${CALL_ID}`);
    // The visible text stays the short id.
    await expect(link).toHaveText(CALL_ID.slice(0, 8));
    // 12.5 of 500 credits.
    await expect(page.getByRole("img", { name: "Budget used: 3%, ₹12.5 of ₹500" })).toBeAttached();
  });
});
