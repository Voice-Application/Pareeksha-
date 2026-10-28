import { test, expect } from "@playwright/test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { KEY, NAV_ITEMS_FOR_SCAN } from "./scan";

// FR-DB-5: the API key is in no client bundle, no HTML and no response seen by the browser.
test("API key absent from .next/static and from every page and response", async ({ page }) => {
  expect(KEY.length).toBeGreaterThan(20);
  const walk = (d: string): string[] =>
    readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]));
  const files = walk(join(process.cwd(), ".next", "static"));
  expect(files.length).toBeGreaterThan(0);
  for (const f of files) expect(readFileSync(f, "utf8"), f).not.toContain(KEY);

  const leaks: string[] = [];
  page.on("response", async (r) => {
    if (!r.url().startsWith("http")) return;
    try {
      if ((await r.text()).includes(KEY)) leaks.push(r.url());
    } catch {
      /* streaming or redirected responses have no body to scan */
    }
  });
  for (const href of NAV_ITEMS_FOR_SCAN) {
    await page.goto(href);
    await page.waitForLoadState("networkidle");
    expect(await page.content()).not.toContain(KEY);
  }
  expect(leaks).toEqual([]);
});
