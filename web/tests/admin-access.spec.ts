import { test, expect } from "@playwright/test";
import { freshState, mockApi } from "./support/mock-api";
import { spawn, type ChildProcess } from "node:child_process";
import { createSessionToken, SESSION_COOKIE, SIGNED_IN_COOKIE, type Role } from "../lib/session";

// The shared build was made with sign-in enabled; exercise that same build in both runtime modes.
const secret = "admin-access-test-session-secret";
const enabledUrl = "http://127.0.0.1:3101";
let enabledServer: ChildProcess;

test.beforeAll(async () => {
  enabledServer = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "-p", "3101", "-H", "127.0.0.1"], {
    env: { ...process.env, AUTH_DISABLED: "0", SESSION_SECRET: secret },
    stdio: "ignore",
  });
  await expect.poll(async () => {
    try { return (await fetch(`${enabledUrl}/login`)).status; } catch { return 0; }
  }, { timeout: 30_000 }).toBe(200);
});

test.afterAll(async () => {
  if (enabledServer && enabledServer.exitCode === null) {
    await new Promise<void>((resolve) => {
      enabledServer.once("exit", () => resolve());
      enabledServer.kill();
    });
  }
});

test.beforeEach(async ({ page }) => {
  await mockApi(page, freshState());
});

for (const role of [undefined, "member", "admin"] as const) {
  test(`open dashboard grants admin controls with ${role ?? "no"} role cookie`, async ({ page }) => {
    if (role) await page.context().addCookies([{ name: SIGNED_IN_COOKIE, value: role, url: "http://127.0.0.1:3100" }]);
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Primary" }).first().getByRole("link", { name: "Users", exact: true })).toBeVisible();
  });
}

for (const role of ["member", "admin"] satisfies Role[]) {
  test(`sign-in enabled preserves ${role} access`, async ({ page }) => {
    const token = await createSessionToken(secret, { id: "test-user", name: "Test", email: "test@example.invalid", role });
    // Cookies are shared across localhost ports; this page uses the sign-in-enabled server.
    await page.context().addCookies([
      { name: SESSION_COOKIE, value: token, url: enabledUrl },
      { name: SIGNED_IN_COOKIE, value: role, url: enabledUrl },
    ]);
    await page.goto(`${enabledUrl}/`);
    await expect(page.getByRole("navigation", { name: "Primary" }).first()).toBeVisible();
    const users = page.getByRole("navigation", { name: "Primary" }).first().getByRole("link", { name: "Users", exact: true });
    if (role === "admin") await expect(users).toBeVisible();
    else await expect(users).toHaveCount(0);
  });
}

test("sign-in enabled hides admin controls without a role cookie", async ({ page }) => {
  const token = await createSessionToken(secret, { id: "test-user", name: "Test", email: "test@example.invalid", role: "member" });
  await page.context().addCookies([{ name: SESSION_COOKIE, value: token, url: enabledUrl }]);
  await page.goto(`${enabledUrl}/`);
  await expect(page.getByRole("navigation", { name: "Primary" }).first()).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" }).first().getByRole("link", { name: "Users", exact: true })).toHaveCount(0);
});
