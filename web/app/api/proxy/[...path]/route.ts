import type { NextRequest } from "next/server";
import { SESSION_COOKIE, sessionSecret, verifySessionToken } from "@/lib/session";
import { normalisePath, requiresAdmin } from "@/lib/admin-routes";
import { refuseCrossSite } from "@/lib/auth-server";

/**
 * BFF proxy (TRD 11, FR-DB-5): the browser calls /api/proxy/<path>; this handler forwards to the origin of
 * PAREEKSHA_API_URL/<path> with the API key added from server env. The key never reaches the
 * browser. The upstream body is passed through as a stream, so SSE works unchanged.
 */
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const FORWARD_REQUEST_HEADERS = ["accept", "content-type", "content-length", "last-event-id", "if-none-match", "range"];
const DROP_RESPONSE_HEADERS = ["set-cookie", "connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length"];

/** Forward one request to the backend API, passing only allow-listed headers and stripping hop-by-hop and cookie response headers. */
async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const base = process.env.PAREEKSHA_API_URL;
  if (!base) {
    return Response.json({ error: "PAREEKSHA_API_URL is not configured" }, { status: 500 });
  }
  const refused = refuseCrossSite(req);
  if (refused) return refused;
  const { path } = await ctx.params;
  if (path.some((seg) => seg === ".." || seg === "." || seg.includes("\\"))) {
    return Response.json({ error: "invalid path" }, { status: 400 });
  }

  // Account endpoints are for the web server only. Every request goes upstream with the admin key, so
  // admin-scoped routes, plus the BFF-only admin paths (see admin-routes.ts), need an admin session.
  // (``health`` stays open: it returns only db/kafka reachability and is the canonical liveness probe.)
  if (normalisePath(path)[0] === "auth") return Response.json({ error: "not found" }, { status: 404 });
  if (process.env.AUTH_DISABLED !== "1" && requiresAdmin(req.method, path)) {
    const secret = sessionSecret();
    const user = secret ? await verifySessionToken(secret, req.cookies.get(SESSION_COOKIE)?.value) : null;
    if (user?.role !== "admin") return Response.json({ error: "admins only" }, { status: 403 });
  }

  const target = new URL(`${new URL(base).origin}/${path.map(encodeURIComponent).join("/")}`);
  target.search = req.nextUrl.search;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const key = process.env.PAREEKSHA_API_KEY;
  if (key) headers.set("authorization", `Bearer ${key}`);

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      // required by undici when streaming a request body
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
      signal: req.signal,
      cache: "no-store",
    } as RequestInit);
  } catch {
    return Response.json({ error: "upstream unreachable" }, { status: 502 });
  }

  const out = new Headers(upstream.headers);
  for (const name of DROP_RESPONSE_HEADERS) out.delete(name);
  out.set("cache-control", "no-store");
  if ((upstream.headers.get("content-type") ?? "").includes("text/event-stream")) {
    out.set("x-accel-buffering", "no");
  }
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: out });
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
