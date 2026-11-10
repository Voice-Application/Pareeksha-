import { test, expect } from "@playwright/test";
import { requiresAdmin } from "../lib/admin-routes";
import { safeNext, sessionSecret } from "../lib/session";
import { isCrossSiteRequest } from "../lib/request-origin";
import { clientAddress, createLimiter } from "../lib/login-throttle";

// Pure functions only: no page fixture, so no browser is launched.
const ID = "00000000-0000-4000-8000-000000000001";
const split = (p: string) => p.split("/").filter(Boolean);

test.describe("requiresAdmin", () => {
  const admin: [string, string][] = [
    ["GET", "api/v1/api-keys"],
    ["POST", "api/v1/api-keys"],
    ["DELETE", `api/v1/api-keys/${ID}`],
    ["POST", `api/v1/dlq/${ID}/replay`],
    ["POST", `api/v1/dlq/${ID}/discard`],
    ["POST", "api/v1/integrations"],
    ["PATCH", `api/v1/integrations/${ID}`],
    ["DELETE", `api/v1/integrations/${ID}`],
    ["POST", `api/v1/integrations/${ID}/test`],
    ["POST", `api/v1/integrations/${ID}/deliveries/${ID}/redeliver`],
    ["PUT", "api/v1/settings/llm"],
    ["DELETE", "api/v1/settings/llm"],
    ["POST", "api/v1/settings/llm/test"],
    ["GET", "api/v1/users"],
    ["POST", "api/v1/users"],
    ["PATCH", `api/v1/users/${ID}`],
    ["GET", "api/v1/metrics/summary"],
    ["HEAD", "api/v1/api-keys"],
  ];
  for (const [method, path] of admin) {
    test(`${method} ${path} needs admin`, () => expect(requiresAdmin(method, split(path))).toBe(true));
  }

  const member: [string, string][] = [
    ["GET", "api/v1/integrations"],
    ["GET", "api/v1/integrations/connectors"],
    ["GET", `api/v1/integrations/${ID}`],
    ["GET", `api/v1/integrations/${ID}/deliveries`],
    ["GET", "api/v1/dlq"],
    ["GET", "api/v1/settings/llm"],
    ["POST", "api/v1/runs"],
    ["POST", "api/v1/quick-tests"],
    ["POST", "api/v1/agents"],
    ["GET", "api/v1/health"],
  ];
  for (const [method, path] of member) {
    test(`${method} ${path} is open to members`, () => expect(requiresAdmin(method, split(path))).toBe(false));
  }

  test("bypass attempts are still matched", () => {
    const attempts: [string, string[]][] = [
      ["POST", ["api", "v1", "API-KEYS"]],
      ["post", ["api", "v1", "api-keys"]],
      ["POST", ["API", "V1", "api-keys"]],
      ["POST", ["api", "v1", "api-keys", ""]],
      ["POST", ["api", "v1", "", "api-keys"]],
      ["POST", ["api", "v1", "api-keys/"]], // decoded from api-keys%2F
      ["POST", ["api/v1/api-keys"]],
      ["POST", ["api-keys"]], // unprefixed form the proxy also forwards
      ["PUT", ["api", "v1", "Settings", "LLM"]],
      ["POST", ["api", "v1", "settings/llm", "test"]],
      ["POST", ["api", "v1", "dlq", ID, "Replay"]],
      ["POST", ["api", "v1", "integrations", ID, "deliveries", ID, "redeliver", ""]],
    ];
    for (const [method, path] of attempts) expect(requiresAdmin(method, path), `${method} ${JSON.stringify(path)}`).toBe(true);
  });
});

test.describe("safeNext", () => {
  const refused = [
    "/\t/evil.example",
    "/\n/evil.example",
    "/\r/evil.example",
    "/\\evil.example",
    "/\\\\evil.example",
    "\\/evil.example",
    "//evil.example",
    "///evil.example",
    "/\t\t/evil.example",
    "/x\u0000y",
    "/x\u0085",
    decodeURIComponent("%2F%09%2Fevil.example"),
    decodeURIComponent("%2F%5Cevil.example"),
    decodeURIComponent("%2F%2Fevil.example"),
    "%2F%2Fevil.example",
    "https://evil.example/",
    "http:/evil.example",
    "evil.example",
    "",
    "/login",
    "/login?next=/x",
  ];
  test("refuses control characters, backslashes, other hosts and the login page", () => {
    for (const next of refused) expect(safeNext(next), JSON.stringify(next)).toBe("/");
  });
  test("null and undefined fall back to /", () => {
    expect(safeNext(null)).toBe("/");
    expect(safeNext(undefined)).toBe("/");
  });
  test("keeps local paths with query and hash", () => {
    expect(safeNext("/")).toBe("/");
    expect(safeNext("/runs")).toBe("/runs");
    expect(safeNext("/runs/compare?a=1&b=two#top")).toBe("/runs/compare?a=1&b=two#top");
    expect(safeNext("/calls/abc?next=https://evil.example")).toBe("/calls/abc?next=https://evil.example");
    expect(safeNext("/%2F%2Fevil.example")).toBe("/%2F%2Fevil.example"); // still a path on this host
    expect(safeNext("/a/../b")).toBe("/b");
  });
});

test.describe("sessionSecret", () => {
  const saved = process.env.SESSION_SECRET;
  test.afterEach(() => {
    if (saved === undefined) delete process.env.SESSION_SECRET;
    else process.env.SESSION_SECRET = saved;
  });
  test("refuses the published default, short and missing values", () => {
    process.env.SESSION_SECRET = "pareeksha-dev-session-secret-change-me";
    expect(sessionSecret()).toBeNull();
    process.env.SESSION_SECRET = "too-short";
    expect(sessionSecret()).toBeNull();
    delete process.env.SESSION_SECRET;
    expect(sessionSecret()).toBeNull();
  });
  test("accepts a real secret", () => {
    process.env.SESSION_SECRET = "a-random-secret-of-enough-length";
    expect(sessionSecret()).toBe("a-random-secret-of-enough-length");
  });
});

test.describe("isCrossSiteRequest", () => {
  const h = (init: Record<string, string>) => new Headers(init);
  test("same origin and non-browser clients pass", () => {
    expect(isCrossSiteRequest("POST", h({ origin: "http://app.example:3000" }), "app.example:3000")).toBe(false);
    expect(isCrossSiteRequest("POST", h({ origin: "https://APP.example" }), "app.example:443")).toBe(false);
    expect(isCrossSiteRequest("DELETE", h({ "sec-fetch-site": "same-origin" }), "app.example")).toBe(false);
    expect(isCrossSiteRequest("POST", h({}), "app.example")).toBe(false);
  });
  test("other origins are refused, including same-site siblings", () => {
    expect(isCrossSiteRequest("POST", h({ origin: "https://evil.example" }), "app.example")).toBe(true);
    expect(isCrossSiteRequest("PUT", h({ origin: "https://other.app.example" }), "app.example")).toBe(true);
    expect(isCrossSiteRequest("PATCH", h({ origin: "http://app.example:3001" }), "app.example:3000")).toBe(true);
    expect(isCrossSiteRequest("POST", h({ origin: "null" }), "app.example")).toBe(true);
    expect(isCrossSiteRequest("POST", h({ "sec-fetch-site": "cross-site" }), "app.example")).toBe(true);
  });
  test("GET and HEAD are never refused", () => {
    expect(isCrossSiteRequest("GET", h({ origin: "https://evil.example" }), "app.example")).toBe(false);
    expect(isCrossSiteRequest("HEAD", h({ "sec-fetch-site": "cross-site" }), "app.example")).toBe(false);
  });
});

test.describe("login throttle", () => {
  test("locks after the limit and expires after the window", () => {
    let t = 0;
    const l = createLimiter(5, { windowMs: 1000, now: () => t });
    for (let i = 0; i < 4; i++) l.fail("a@example.invalid");
    expect(l.locked("a@example.invalid")).toBe(false);
    l.fail("a@example.invalid");
    expect(l.locked("a@example.invalid")).toBe(true);
    expect(l.locked("b@example.invalid")).toBe(false);
    t = 1001;
    expect(l.locked("a@example.invalid")).toBe(false);
  });
  test("the map is pruned of expired entries and capped", () => {
    let t = 0;
    const l = createLimiter(5, { windowMs: 1000, maxEntries: 3, now: () => t });
    l.fail("a");
    l.fail("b");
    t = 1500;
    l.fail("c");
    expect(l.size()).toBe(1);
    l.fail("d");
    l.fail("e");
    l.fail("f");
    expect(l.size()).toBe(3);
    for (let i = 0; i < 5; i++) l.fail("f");
    expect(l.locked("f")).toBe(true);
  });
  test("X-Forwarded-For is ignored unless trusted", () => {
    const headers = new Headers({ "x-forwarded-for": "203.0.113.9, 10.0.0.1" });
    expect(clientAddress(headers, false)).toBeNull();
    expect(clientAddress(headers, true)).toBe("203.0.113.9");
  });
});
