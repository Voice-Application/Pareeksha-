// Render docs/design/mock-call-detail.html to PNG (light + dark, desktop + phone).
// Run: PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node proof/DES-01/screenshots.js
const path = require('path');
let pw;
try { pw = require('playwright'); } catch (e) { pw = require('/opt/node-tools/node_modules/playwright'); }
const { chromium } = pw;

const root = path.resolve(__dirname, '..', '..');
const file = 'file://' + path.join(root, 'docs/design/mock-call-detail.html');
const out = __dirname;

(async () => {
  const browser = await chromium.launch();
  const shots = [
    { name: 'call-detail-light-1440', theme: 'light', w: 1440, h: 900, full: true },
    { name: 'call-detail-dark-1440', theme: 'dark', w: 1440, h: 900, full: true },
    { name: 'call-detail-light-390', theme: 'light', w: 390, h: 844, full: true },
    { name: 'call-detail-dark-390', theme: 'dark', w: 390, h: 844, full: true },
    { name: 'call-detail-light-fold', theme: 'light', w: 1440, h: 900, full: false },
    { name: 'call-detail-dark-fold', theme: 'dark', w: 1440, h: 900, full: false },
  ];
  for (const s of shots) {
    const ctx = await browser.newContext({ viewport: { width: s.w, height: s.h }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto(file + '?theme=' + s.theme);
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(out, s.name + '.png'), fullPage: s.full });
    const hscroll = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    console.log(s.name, 'horizontal-scroll=' + hscroll, 'console-errors=' + errors.length);
    await ctx.close();
  }
  await browser.close();
})();
