import type { NextRequest } from "next/server";

/**
 * BFF proxy (TRD 11, FR-DB-5): the browser calls /api/proxy/<path>; this handler forwards to the origin of
 * PAREEKSHA_API_URL/<path> with the API key added from server env. The key never reaches the
 * browser. The upstream body is passed through as a stream, so SSE works unchanged.
 */
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const FORWARD_REQUEST_HEADERS = ["accept", "content-type", "content-length", "last-event-id", "if-none-match", "range"];
const DROP_RESPONSE_HEADERS = ["set-cookie", "connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length"];

async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const base = process.env.PAREEKSHA_API_URL;
  if (!base) {
    return Response.json({ error: "PAREEKSHA_API_URL is not configured" }, { status: 500 });
  }
  const { path } = await ctx.params;
  if (path.some((seg) => seg === ".." || seg === "." || seg.includes("\\"))) {
    return Response.json({ error: "invalid path" }, { status: 400 });
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
