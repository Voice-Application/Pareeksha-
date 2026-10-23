import { test, expect } from "@playwright/test";
import { createServer, type Server, type IncomingHttpHeaders } from "node:http";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { NAV_ITEMS } from "../lib/nav";

// Local upstream standing in for FastAPI (test-only): records what the proxy forwards.
let upstream: Server;
const seen: { url: string; headers: IncomingHttpHeaders }[] = [];

test.beforeAll(async () => {
  upstream = createServer((req, res) => {
    seen.push({ url: req.url ?? "", headers: req.headers });
    if (req.url?.startsWith("/api/v1/runs/r1/events")) {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
      res.write("event: item\ndata: {\"n\":1}\n\n");
      setTimeout(() => {
        res.write("event: item\ndata: {\"n\":2}\n\n");
        res.end();
      }, 700);
      return;
    }
    res.writeHead(200, { "content-type": "application/json", "set-cookie": "leak=1" });
    res.end(JSON.stringify({ db: "ok", kafka: "ok" }));
  });
  await new Promise<void>((r) => upstream.listen(3199, "127.0.0.1", r));
});
test.afterAll(async () => {
  await new Promise<void>((r) => upstream.close(() => r()));
});

for (const item of NAV_ITEMS) {
  test(`page ${item.href} renders inside layout with sidebar`, async ({ page }) => {
    const res = await page.goto(item.href);
    expect(res?.status()).toBe(200);
    const nav = page.getByRole("navigation", { name: "Primary" });
    await expect(nav).toBeVisible();
    await expect(nav.getByRole("link", { name: item.label, exact: true })).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("heading", { level: 1, name: item.label, exact: true })).toBeVisible();
  });
}

test("sidebar links navigate client-side to every route", async ({ page }) => {
  await page.goto("/");
  for (const item of NAV_ITEMS) {
    await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: item.label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${item.href === "/" ? "/$" : item.href + "$"}`));
  }
});

test("proxy adds API key server-side and strips set-cookie", async ({ request }) => {
  seen.length = 0;
  const res = await request.get("/api/proxy/api/v1/health?x=1");
  expect(res.status()).toBe(200);
  expect(await res.json()).toEqual({ db: "ok", kafka: "ok" });
  expect(res.headers()["set-cookie"]).toBeUndefined();
  expect(seen[0].url).toBe("/api/v1/health?x=1");
  expect(seen[0].headers.authorization).toBe("Bearer pk_test_fe01_secret");
});

test("proxy ignores a client-supplied Authorization header", async ({ request }) => {
  seen.length = 0;
  await request.get("/api/proxy/api/v1/health", { headers: { authorization: "Bearer attacker" } });
  expect(seen[0].headers.authorization).toBe("Bearer pk_test_fe01_secret");
});

test("proxy streams SSE incrementally", async ({ page }) => {
  await page.goto("/");
  const timings = await page.evaluate(async () => {
    const t0 = performance.now();
    const res = await fetch("/api/proxy/api/v1/runs/r1/events");
    const reader = res.body!.getReader();
    const marks: number[] = [];
    const dec = new TextDecoder();
    let text = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      text += dec.decode(value);
      marks.push(Math.round(performance.now() - t0));
    }
    return { ct: res.headers.get("content-type"), marks, text };
  });
  expect(timings.ct).toContain("text/event-stream");
  expect(timings.text).toContain('"n":1');
  expect(timings.text).toContain('"n":2');
  expect(timings.marks.length).toBeGreaterThanOrEqual(2);
  expect(timings.marks[timings.marks.length - 1] - timings.marks[0]).toBeGreaterThan(400);
});

test("API key is absent from pages and client bundles", async ({ page }) => {
  const html = await (await page.goto("/"))!.text();
  expect(html).not.toContain("pk_test_fe01_secret");
  const staticDir = join(process.cwd(), ".next", "static");
  const walk = (d: string): string[] =>
    readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]));
  const files = walk(staticDir);
  expect(files.length).toBeGreaterThan(0);
  for (const f of files) expect(readFileSync(f, "utf8")).not.toContain("pk_test_fe01_secret");
});
