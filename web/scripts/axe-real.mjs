// axe (wcag2a + wcag2aa) on pages of the real stack, light and dark: node scripts/axe-real.mjs <out.json> <path> ...
import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { writeFileSync } from "node:fs";

const [out, ...paths] = process.argv.slice(2);
const base = process.env.BASE_URL ?? "http://127.0.0.1:3100";
const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined });
const report = [];
for (const scheme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: scheme });
  const page = await ctx.newPage();
  for (const p of paths) {
    await page.goto(base + p, { waitUntil: "networkidle" });
    await page.waitForTimeout(800);
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    report.push({ path: p, scheme, violations: r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, first: v.nodes[0]?.html.slice(0, 140) })) });
  }
  await ctx.close();
}
await browser.close();
writeFileSync(out, JSON.stringify(report, null, 2));
const bad = report.filter((r) => r.violations.length);
console.log(`${report.length} page-themes checked, ${bad.length} with violations`);
for (const b of bad) console.log(b.path, b.scheme, JSON.stringify(b.violations));
process.exit(bad.length ? 1 : 0);
