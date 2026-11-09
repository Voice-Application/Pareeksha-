import { test, expect, type BrowserContext } from "@playwright/test";
import { mockFe, opsState } from "./support/fe03-mock";
import { createSessionToken, SESSION_COOKIE, SIGNED_IN_COOKIE, type Role } from "../lib/session";
import { signInEnabledServer } from "./support/enabled-server";

// On the open dashboard (:3100) everyone is an admin, so role-driven UI is tested with sign-in enabled.
const secret = "overview-role-test-session-secret";
const enabled = signInEnabledServer(3102, secret);
const url = enabled.url;

test.beforeAll(() => enabled.start());
test.afterAll(() => enabled.stop());

// The signed session lets pages past the gate; the readable role cookie is the client-side hint the UI follows.
async function signIn(context: BrowserContext, sessionRole: Role, hint: string) {
  const token = await createSessionToken(secret, { id: "test-user", name: "Test", email: "test@example.invalid", role: sessionRole });
  await context.addCookies([
    { name: SESSION_COOKIE, value: token, url },
    { name: SIGNED_IN_COOKIE, value: hint, url },
  ]);
}

for (const fallback of [false, true]) {
  test(`overview follows role changes from another tab${fallback ? " without Cookie Store" : ""}`, async ({ page, context }) => {
    if (fallback) await context.addInitScript(() => { Reflect.deleteProperty(window, "cookieStore"); });
    await signIn(context, "admin", "admin");
    await mockFe(page, opsState());
    let telemetryRequests = 0;
    page.on("request", (request) => {
      if (/\/api\/v1\/(metrics\/summary|health)(?:\?|$)/.test(request.url())) telemetryRequests++;
    });
    await page.goto(`${url}/`);
    const health = page.getByRole("heading", { name: "Platform health", exact: true });
    const dlq = page.getByRole("link", { name: /Open DLQ items/ });
    await expect(health).toBeVisible();
    await expect(dlq).toBeVisible();
    await expect.poll(() => telemetryRequests).toBeGreaterThanOrEqual(2);

    const other = await context.newPage();
    await mockFe(other, opsState());
    await other.goto(`${url}/`);
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
    await signIn(context, "member", role);
    await mockFe(page, opsState());
    const telemetry: string[] = [];
    page.on("request", (request) => {
      if (/\/api\/v1\/(metrics\/summary|health)(?:\?|$)/.test(request.url())) telemetry.push(request.url());
    });
    await page.goto(`${url}/`);
    await expect(page.getByRole("heading", { name: "Recent runs", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Platform health", exact: true })).toBeHidden();
    await expect(page.getByRole("link", { name: /Open DLQ items/ })).toBeHidden();
    expect(telemetry).toEqual([]);
  });
}
