import { test, expect, type APIRequestContext, type BrowserContext } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { createSessionToken, SESSION_COOKIE, SIGNED_IN_COOKIE, type Role } from "../lib/session";
import { signInEnabledServer } from "./support/enabled-server";
import { mockFe, opsState } from "./support/fe03-mock";
import { uuid } from "./support/mock-api";

// The BFF with sign-in enabled, in front of a recording upstream (not page.route: the proxy itself is under test).
const secret = "security-proxy-test-session-secret";
const UPSTREAM_PORT = 3197;
const enabled = signInEnabledServer(3103, secret, { PAREEKSHA_API_URL: `http://127.0.0.1:${UPSTREAM_PORT}/api/v1`, PAREEKSHA_API_KEY: "pk_test_security" });
const defaultSecret = signInEnabledServer(3104, "pareeksha-dev-session-secret-change-me");
const url = enabled.url;
const ID = uuid(7);

let upstream: Server;
const seen: { method: string; path: string; auth?: string }[] = [];

test.beforeAll(async () => {
  test.setTimeout(240_000);
  upstream = createServer((req, res) => {
    seen.push({ method: req.method!, path: req.url!, auth: req.headers.authorization });
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      res.setHeader("content-type", "application/json");
      if (req.url === "/api/v1/auth/login") {
        const { email, password } = JSON.parse(body) as { email: string; password: string };
        if (password !== "right-password") return res.writeHead(401).end(JSON.stringify({ error: { code: "unauthorized" } }));
        return res.end(JSON.stringify({ id: "u1", name: "User", email, role: "member" }));
      }
      res.end(JSON.stringify({ ok: true }));
    });
  });
  await new Promise<void>((r) => upstream.listen(UPSTREAM_PORT, "127.0.0.1", r));
  await Promise.all([enabled.start(), defaultSecret.start()]);
});
test.afterAll(async () => {
  await Promise.all([enabled.stop(), defaultSecret.stop()]);
  await new Promise((r) => upstream.close(r));
});

const cookieFor = async (role: Role) => `${SESSION_COOKIE}=${await createSessionToken(secret, { id: `${role}-1`, name: role, email: `${role}@example.invalid`, role })}`;

async function send(request: APIRequestContext, role: Role, method: string, path: string, headers: Record<string, string> = {}) {
  return request.fetch(`${url}/api/proxy/${path}`, { method, headers: { cookie: await cookieFor(role), "content-type": "application/json", ...headers }, data: method === "GET" ? undefined : "{}", maxRedirects: 0 });
}
const forwarded = (path: string) => seen.some((s) => s.path.startsWith(`/${path}`));

const ADMIN_OPS: [string, string][] = [
  ["POST", "api/v1/api-keys"],
  ["PUT", "api/v1/settings/llm"],
  ["POST", "api/v1/integrations"],
  ["POST", `api/v1/dlq/${ID}/replay`],
  ["POST", `api/v1/integrations/${ID}/test`],
  ["POST", `api/v1/integrations/${ID}/deliveries/${ID}/redeliver`],
];

test("a member gets 403 for admin-scoped routes, which never reach the API", async ({ request }) => {
  seen.length = 0;
  for (const [method, path] of ADMIN_OPS) {
    const res = await send(request, "member", method, path);
    expect(res.status(), `${method} ${path}`).toBe(403);
  }
  for (const path of ["api/v1/API-KEYS", "api/v1/api-keys%2F", "api/v1/api-keys/", "api/v1//api-keys", "api-keys"]) {
    const res = await send(request, "member", "POST", path);
    // Next.js may first redirect to the canonical path, which is then checked like any other request.
    if (res.status() === 308) expect(res.headers()["location"], path).toBe("/api/proxy/api/v1/api-keys");
    else expect(res.status(), path).toBe(403);
  }
  expect(seen).toEqual([]);
});

test("a member keeps read and run routes", async ({ request }) => {
  seen.length = 0;
  for (const [method, path] of [["GET", "api/v1/integrations"], ["GET", "api/v1/dlq"], ["GET", "api/v1/settings/llm"], ["POST", "api/v1/runs"], ["POST", "api/v1/quick-tests"]]) {
    const res = await send(request, "member", method, path);
    expect(res.status(), `${method} ${path}`).toBe(200);
    expect(forwarded(path)).toBe(true);
  }
  expect(seen.every((s) => s.auth === "Bearer pk_test_security")).toBe(true);
});

test("an admin can still perform admin operations", async ({ request }) => {
  seen.length = 0;
  for (const [method, path] of ADMIN_OPS) {
    const res = await send(request, "admin", method, path);
    expect(res.status(), `${method} ${path}`).toBe(200);
    expect(forwarded(path)).toBe(true);
  }
});

test("state-changing requests from another site are refused", async ({ request }) => {
  seen.length = 0;
  expect((await send(request, "member", "POST", "api/v1/runs", { origin: "https://evil.example" })).status()).toBe(403);
  expect((await send(request, "member", "POST", "api/v1/runs", { origin: "http://127.0.0.1:3199" })).status()).toBe(403);
  expect((await send(request, "member", "POST", "api/v1/runs", { "sec-fetch-site": "cross-site" })).status()).toBe(403);
  expect(seen).toEqual([]);
  expect((await send(request, "member", "POST", "api/v1/runs", { origin: url, "sec-fetch-site": "same-origin" })).status()).toBe(200);
  expect((await send(request, "member", "GET", "api/v1/runs", { origin: "https://evil.example" })).status()).toBe(200);
  for (const path of ["/api/auth/login", "/api/auth/logout", "/api/auth/setup"]) {
    const res = await request.post(`${url}${path}`, { form: { email: "a@example.invalid", password: "x" }, headers: { origin: "https://evil.example" }, maxRedirects: 0 });
    expect(res.status(), path).toBe(403);
  }
  const logout = await request.post(`${url}/api/auth/logout`, { headers: { origin: url }, maxRedirects: 0 });
  expect(logout.status()).toBe(303);
});

async function login(request: APIRequestContext, email: string, password: string, extra: Record<string, string> = {}, headers: Record<string, string> = {}) {
  const res = await request.post(`${url}/api/auth/login`, { form: { email, password, ...extra }, headers, maxRedirects: 0 });
  expect(res.status()).toBe(303);
  return new URL(res.headers()["location"]);
}

test("sign-in throttles per account even when X-Forwarded-For rotates", async ({ request }) => {
  test.setTimeout(60_000);
  const email = "victim@example.invalid";
  for (let i = 0; i < 5; i++) {
    const loc = await login(request, email, "wrong", {}, { "x-forwarded-for": `198.51.100.${i}` });
    expect(loc.searchParams.get("error")).toBe("wrong");
  }
  const locked = await login(request, email.toUpperCase(), "right-password", {}, { "x-forwarded-for": "198.51.100.200" });
  expect(locked.searchParams.get("error")).toBe("locked");
  // Another account from the same client is unaffected.
  const other = await login(request, "someone@example.invalid", "right-password");
  expect(other.pathname).toBe("/");
  expect(other.searchParams.get("error")).toBeNull();
});

test("sign-in sends unsafe next values home", async ({ request }) => {
  for (const next of ["/\t/evil.example", "/\n/evil.example", "/\\evil.example", "//evil.example", "https://evil.example/"]) {
    const loc = await login(request, "next@example.invalid", "right-password", { next });
    expect(loc.host, JSON.stringify(next)).toBe("127.0.0.1:3103");
    expect(loc.pathname).toBe("/");
  }
  const ok = await login(request, "next@example.invalid", "right-password", { next: "/runs?status=failed" });
  expect(ok.pathname + ok.search).toBe("/runs?status=failed");
});

test("security headers are set on pages and API routes", async ({ request }) => {
  const cookie = await cookieFor("member");
  for (const path of ["/login", "/api/proxy/api/v1/health"]) {
    const h = (await request.get(`${url}${path}`, { headers: { cookie } })).headers();
    expect(h["x-content-type-options"], path).toBe("nosniff");
    expect(h["referrer-policy"], path).toBe("strict-origin-when-cross-origin");
    expect(h["x-frame-options"], path).toBe("DENY");
    expect(h["content-security-policy"], path).toBe("frame-ancestors 'none'");
    expect(h["permissions-policy"], path).toBe("camera=(), geolocation=()");
    expect(h["strict-transport-security"], path).toBeUndefined();
  }
  const https = (await request.get(`${url}/login`, { headers: { "x-forwarded-proto": "https" } })).headers();
  expect(https["strict-transport-security"]).toBe("max-age=31536000");
});

test("the published default SESSION_SECRET is refused", async ({ request }) => {
  const forged = await createSessionToken("pareeksha-dev-session-secret-change-me", { id: "x", name: "x", email: "x@example.invalid", role: "admin" });
  const res = await request.get(`${defaultSecret.url}/`, { headers: { cookie: `${SESSION_COOKIE}=${forged}` }, maxRedirects: 0 });
  expect(res.status()).toBe(503);
  expect(await res.text()).toContain("SESSION_SECRET");
});

async function signInAs(context: BrowserContext, role: Role) {
  const token = await createSessionToken(secret, { id: `${role}-1`, name: role, email: `${role}@example.invalid`, role });
  await context.addCookies([{ name: SESSION_COOKIE, value: token, url }, { name: SIGNED_IN_COOKIE, value: role, url }]);
}

for (const role of ["member", "admin"] satisfies Role[]) {
  test(`${role} sees ${role === "admin" ? "" : "no "}admin-only controls`, async ({ page, context }) => {
    await signInAs(context, role);
    const st = opsState();
    const ts = "2026-10-20T10:00:00Z";
    st.extra["GET /integrations/connectors"] = [{ name: "webhook", direction: "both", subscribes_to: [], config_schema: { properties: {} }, secrets_schema: { properties: {} } }];
    st.extra["GET /integrations"] = { items: [{ id: ID, connector: "webhook", name: "Hook", direction: "both", enabled: true, config: {}, secrets_set: false, event_filter: { events: [], only_failed: false }, last_test_at: null, last_test_ok: null, created_at: ts, updated_at: ts }], next_cursor: null };
    await mockFe(page, st);
    const visible = role === "admin" ? 1 : 0;

    await page.goto(`${url}/integrations`);
    await expect(page.getByRole("table", { name: "Integrations" })).toContainText("Hook");
    await expect(page.getByRole("button", { name: "Add integration" })).toHaveCount(visible);

    await page.goto(`${url}/dlq`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Replay all open" })).toHaveCount(visible);

    const nav = page.getByRole("navigation", { name: "Primary" }).first();
    await expect(nav.getByRole("link", { name: "API keys", exact: true })).toHaveCount(visible);
    await page.goto(`${url}/settings/api-keys`);
    if (role === "admin") await expect(page).toHaveURL(`${url}/settings/api-keys`);
    else await expect(page).toHaveURL(`${url}/`);
  });
}
