// Screenshots of pages against the real stack: node scripts/shots.mjs <outDir> <path>=<name> ...  (light + dark, 1440 wide)
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const [out, ...pairs] = process.argv.slice(2);
const base = process.env.BASE_URL ?? "http://127.0.0.1:3100";
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined });
for (const scheme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: scheme });
  const page = await ctx.newPage();
  for (const pair of pairs) {
    const i = pair.lastIndexOf("="); const path = pair.slice(0, i); const name = pair.slice(i + 1);
    await page.goto(base + path, { waitUntil: "networkidle" });
    await page.waitForTimeout(600);
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.setViewportSize({ width: 1440, height: Math.max(900, h) });
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${out}/${name}-${scheme}.png`, fullPage: false });
  }
  await ctx.close();
}
await browser.close();
