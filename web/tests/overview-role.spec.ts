import { test, expect } from "@playwright/test";
import { mockFe, opsState } from "./support/fe03-mock";

for (const fallback of [false, true]) {
  test(`overview follows role changes from another tab${fallback ? " without Cookie Store" : ""}`, async ({ page, context }) => {
    if (fallback) await context.addInitScript(() => { Reflect.deleteProperty(window, "cookieStore"); });
    await context.addCookies([{ name: "pareeksha_signed_in", value: "admin", url: "http://127.0.0.1:3100" }]);
    await mockFe(page, opsState());
    let telemetryRequests = 0;
    page.on("request", (request) => {
      if (/\/api\/v1\/(metrics\/summary|health)(?:\?|$)/.test(request.url())) telemetryRequests++;
    });
    await page.goto("/");
    const health = page.getByRole("heading", { name: "Platform health", exact: true });
    const dlq = page.getByRole("link", { name: /Open DLQ items/ });
    await expect(health).toBeVisible();
    await expect(dlq).toBeVisible();
    await expect.poll(() => telemetryRequests).toBeGreaterThanOrEqual(2);

    const other = await context.newPage();
    await mockFe(other, opsState());
    await other.goto("/");
    await other.evaluate(() => { document.cookie = "pareeksha_signed_in=member; Path=/"; });
    await expect(health).toBeHidden();
    await expect(dlq).toBeHidden();
    await page.clock.install();
    const afterDowngrade = telemetryRequests;
    await page.clock.fastForward(16000);
    expect(telemetryRequests).toBe(afterDowngrade);

    await other.evaluate(() => { document.cookie = "pareeksha_signed_in=admin; Path=/"; });
    // Advance the fallback timer as well as letting native cookie events arrive.
    await page.clock.runFor(1100);
    await expect(health).toBeVisible();
    await expect(dlq).toBeVisible();
  });
}

for (const role of ["member", "unknown"]) {
  test(`overview hides admin controls for ${role}`, async ({ page, context }) => {
    await context.addCookies([{ name: "pareeksha_signed_in", value: role, url: "http://127.0.0.1:3100" }]);
    await mockFe(page, opsState());
    const telemetry: string[] = [];
    page.on("request", (request) => {
      if (/\/api\/v1\/(metrics\/summary|health)(?:\?|$)/.test(request.url())) telemetry.push(request.url());
    });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Recent runs", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Platform health", exact: true })).toBeHidden();
    await expect(page.getByRole("link", { name: /Open DLQ items/ })).toBeHidden();
    expect(telemetry).toEqual([]);
  });
}
