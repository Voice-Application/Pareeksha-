import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { freshState, mockApi, uuid, type MockState } from "./support/mock-api";

/**
 * Screenshots for proof/FE-02 (light and dark) plus accessibility and "no banned styles" checks.
 * Data comes from the Playwright route fixture in support/mock-api.ts, NOT from the real backend:
 * the real-data screenshot step is pending API-02 (see proof/FE-02/proof.md).
 */
const OUT = join(process.cwd(), "..", "proof", "FE-02", "screenshots");
mkdirSync(OUT, { recursive: true });

type View = { name: string; path: string; mutate?: (s: MockState) => void; ready: (p: Page) => Promise<void>; act?: (p: Page) => Promise<void> };

const VIEWS: View[] = [
  { name: "agents-list", path: "/agents", ready: async (p) => void (await expect(p.getByRole("link", { name: "EMI Reminder Bot" })).toBeVisible()), act: async (p) => {
      await p.getByRole("button", { name: "Actions for EMI Reminder Bot" }).click();
      await p.getByRole("menuitem", { name: "Test connection" }).click();
      await expect(p.getByRole("row", { name: /EMI Reminder Bot/ })).toContainText("ok 820 ms");
    } },
  { name: "agent-edit", path: `/agents/${uuid(101)}`, ready: async (p) => void (await expect(p.locator("#agent-name")).toHaveValue("EMI Reminder Bot")), act: async (p) => {
      await p.getByRole("button", { name: "Test connection" }).click();
      await expect(p.getByText("pareeksha-audio-v1")).toBeVisible();
    } },
  { name: "agent-new-validation", path: "/agents/new", ready: async (p) => void (await expect(p.getByRole("button", { name: "Create agent" })).toBeVisible()), act: async (p) => {
      await p.getByRole("button", { name: "Add disclosure" }).click();
      await p.getByRole("button", { name: "Create agent" }).click();
      await expect(p.getByRole("alert").filter({ hasText: "Fix" })).toBeVisible();
    } },
  { name: "scenarios-list", path: "/scenarios", ready: async (p) => void (await expect(p.getByRole("link", { name: "Abusive caller" })).toBeVisible()) },
  { name: "scenario-edit", path: `/scenarios/${uuid(201)}`, ready: async (p) => void (await expect(p.locator("#sc-title")).toHaveValue("Already paid, wants confirmation")) },
  { name: "scenarios-generate-review", path: "/scenarios", ready: async (p) => void (await expect(p.getByRole("link", { name: "Abusive caller" })).toBeVisible()), act: async (p) => {
      await p.getByRole("button", { name: "Generate with AI" }).click();
      await p.getByRole("button", { name: "Generate", exact: true }).click();
      await expect(p.getByText("Customer disputes the late fee")).toBeVisible();
    } },
  { name: "personas-list", path: "/personas", ready: async (p) => void (await expect(p.getByRole("link", { name: "Custom English" })).toBeVisible()) },
  { name: "persona-sheet", path: `/personas?edit=${uuid(301)}`, ready: async (p) => void (await expect(p.getByRole("dialog", { name: "Manju, frustrated Kanglish" })).toBeVisible()) },
  { name: "noise-profiles-list", path: "/noise-profiles", ready: async (p) => void (await expect(p.getByRole("link", { name: "clean_16k" })).toBeVisible()) },
  { name: "noise-profile-sheet", path: `/noise-profiles?edit=${uuid(402)}`, ready: async (p) => void (await expect(p.getByRole("dialog", { name: "pstn_market_5db" })).toBeVisible()) },
];

const STATES: { name: string; path: string; mutate: (s: MockState) => void; ready: (p: Page) => Promise<void> }[] = [
  { name: "agents-empty", path: "/agents", mutate: (s) => (s.agents = []), ready: async (p) => void (await expect(p.getByRole("heading", { name: "No agents yet" })).toBeVisible()) },
  { name: "agents-error", path: "/agents", mutate: (s) => (s.fail = [{ match: "GET /agents", status: 500, message: "The database is unavailable." }]), ready: async (p) => void (await expect(p.getByText("Could not load agents")).toBeVisible()) },
  { name: "agents-loading", path: "/agents", mutate: (s) => (s.delay = 8000), ready: async (p) => void (await expect(p.getByRole("status", { name: "Loading agents" })).toBeVisible()) },
  { name: "scenarios-empty", path: "/scenarios", mutate: (s) => (s.scenarios = []), ready: async (p) => void (await expect(p.getByRole("heading", { name: "No scenarios yet" })).toBeVisible()) },
  { name: "scenarios-error", path: "/scenarios", mutate: (s) => (s.fail = [{ match: "GET /scenarios", status: 500, message: "The database is unavailable." }]), ready: async (p) => void (await expect(p.getByText("Could not load scenarios")).toBeVisible()) },
  { name: "scenarios-loading", path: "/scenarios", mutate: (s) => (s.delay = 8000), ready: async (p) => void (await expect(p.getByRole("status", { name: "Loading scenarios" })).toBeVisible()) },
  { name: "personas-empty", path: "/personas", mutate: (s) => (s.personas = []), ready: async (p) => void (await expect(p.getByRole("heading", { name: "No personas yet" })).toBeVisible()) },
  { name: "personas-error", path: "/personas", mutate: (s) => (s.fail = [{ match: "GET /personas", status: 500, message: "The database is unavailable." }]), ready: async (p) => void (await expect(p.getByText("Could not load personas")).toBeVisible()) },
  { name: "personas-loading", path: "/personas", mutate: (s) => (s.delay = 8000), ready: async (p) => void (await expect(p.getByRole("status", { name: "Loading personas" })).toBeVisible()) },
  { name: "noise-profiles-empty", path: "/noise-profiles", mutate: (s) => (s.noise = []), ready: async (p) => void (await expect(p.getByRole("heading", { name: "No noise profiles" })).toBeVisible()) },
  { name: "noise-profiles-error", path: "/noise-profiles", mutate: (s) => (s.fail = [{ match: "GET /noise-profiles", status: 500, message: "The database is unavailable." }]), ready: async (p) => void (await expect(p.getByText("Could not load noise profiles")).toBeVisible()) },
  { name: "noise-profiles-loading", path: "/noise-profiles", mutate: (s) => (s.delay = 8000), ready: async (p) => void (await expect(p.getByRole("status", { name: "Loading noise profiles" })).toBeVisible()) },
];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`screenshots ${scheme}`, () => {
    test.use({ viewport: { width: 1440, height: 900 }, colorScheme: scheme });

    for (const v of VIEWS) {
      test(`${v.name} (${scheme})`, async ({ page }) => {
        const state = freshState();
        v.mutate?.(state);
        await mockApi(page, state);
        await page.goto(v.path);
        await v.ready(page);
        await v.act?.(page);
        await expect(page.locator("html")).toHaveClass(scheme === "dark" ? /dark/ : /^(?!.*dark).*$/);
        await page.screenshot({ path: join(OUT, `${v.name}-${scheme}.png`) });
      });
    }

    for (const st of STATES) {
      test(`${st.name} (${scheme})`, async ({ page }) => {
        const state = freshState();
        st.mutate(state);
        await mockApi(page, state);
        await page.goto(st.path);
        await st.ready(page);
        await page.screenshot({ path: join(OUT, `${st.name}-${scheme}.png`) });
      });
    }
  });
}

test.describe("phone width", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  for (const [name, path, link] of [
    ["agents-list", "/agents", "EMI Reminder Bot"],
    ["scenarios-list", "/scenarios", "Abusive caller"],
    ["personas-list", "/personas", "Custom English"],
    ["noise-profiles-list", "/noise-profiles", "clean_16k"],
  ] as const) {
    test(`${name} stacks into cards without sideways page scroll`, async ({ page }) => {
      await mockApi(page, freshState());
      await page.goto(path);
      await expect(page.getByRole("link", { name: link })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
      // Header row is visually hidden at phone width (rows become labelled cards).
      const box = await page.locator("table.rt thead").first().boundingBox();
      expect(box === null || box.width <= 1).toBe(true);
      await page.screenshot({ path: join(OUT, `${name}-phone-light.png`) });
    });
  }
});

test.describe("accessibility and visual rules", () => {
  const PAGES = ["/agents", `/agents/${uuid(101)}`, "/scenarios", `/scenarios/${uuid(201)}`, "/personas", "/noise-profiles"];
  for (const scheme of ["light", "dark"] as const) {
    for (const path of PAGES) {
      test(`axe: no serious or critical violations on ${path} (${scheme})`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: scheme });
        await mockApi(page, freshState());
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expect(page.getByRole("status", { name: /Loading/ })).toHaveCount(0);
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
        const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
      });
    }
  }

  test("no gradients, no emoji, no card shadows on any FE-02 page", async ({ page }) => {
    await mockApi(page, freshState());
    for (const path of ["/agents", `/agents/${uuid(101)}`, "/scenarios", `/scenarios/${uuid(201)}`, "/personas", "/noise-profiles"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByRole("status", { name: /Loading/ })).toHaveCount(0);
      const found = await page.evaluate(() => {
        const bad: string[] = [];
        const emoji = /\p{Extended_Pictographic}/u;
        for (const el of Array.from(document.body.querySelectorAll("*"))) {
          const cs = getComputedStyle(el);
          if (cs.backgroundImage.includes("gradient")) bad.push(`gradient on ${el.tagName}`);
          if (cs.boxShadow !== "none" && el.closest("section, table")) bad.push(`shadow on ${el.tagName}.${(el as HTMLElement).className}`);
          if (el.children.length === 0 && emoji.test(el.textContent ?? "")) bad.push(`emoji in ${el.tagName}`);
        }
        return bad;
      });
      expect(found, path).toEqual([]);
    }
  });

  test("the whole list page can be driven with the keyboard", async ({ page }) => {
    await mockApi(page, freshState());
    await page.goto("/agents");
    await expect(page.getByRole("link", { name: "EMI Reminder Bot" })).toBeVisible();
    // Skip link first, then the sidebar, topbar, then the page.
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
    await page.keyboard.press("Enter");
    const focusRing = await page.evaluate(() => {
      const cs = getComputedStyle(document.activeElement as Element);
      return { outlineStyle: cs.outlineStyle, outlineWidth: cs.outlineWidth };
    });
    expect(focusRing.outlineStyle === "none" || focusRing.outlineStyle === "solid").toBe(true);
    await page.getByRole("searchbox", { name: "Search agents" }).focus();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Adapter", { exact: true })).toBeFocused();
    const ring = await page.evaluate(() => getComputedStyle(document.activeElement as Element).outlineWidth);
    expect(ring).toBe("2px");
  });

  test("theme toggle switches and remembers the choice", async ({ page }) => {
    await mockApi(page, freshState());
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/agents");
    await page.getByRole("button", { name: "Switch to dark theme" }).click();
    await expect(page.locator("html")).toHaveClass(/dark/);
    await page.reload();
    await expect(page.locator("html")).toHaveClass(/dark/);
    await page.getByRole("button", { name: "Switch to light theme" }).click();
    await expect(page.locator("html")).not.toHaveClass(/dark/);
  });
});
