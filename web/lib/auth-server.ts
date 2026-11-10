import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, SESSION_MAX_AGE_S, SIGNED_IN_COOKIE, createSessionToken, sessionSecret, type SessionUser } from "@/lib/session";
import { isCrossSiteRequest } from "@/lib/request-origin";

/** The account endpoints of the backend, called with the server's own API key. Browsers never reach them. */
export async function backend(path: string, init: { method?: string; body?: unknown } = {}): Promise<{ status: number; data: unknown }> {
  const base = process.env.PAREEKSHA_API_URL;
  if (!base) return { status: 500, data: { message: "PAREEKSHA_API_URL is not configured" } };
  try {
    const res = await fetch(new URL(`/api/v1${path}`, new URL(base).origin), {
      method: init.method ?? (init.body ? "POST" : "GET"),
      headers: { authorization: `Bearer ${process.env.PAREEKSHA_API_KEY ?? ""}`, "content-type": "application/json" },
      body: init.body ? JSON.stringify(init.body) : undefined,
      cache: "no-store",
    });
    return { status: res.status, data: await res.json().catch(() => ({})) };
  } catch {
    return { status: 502, data: { message: "The API is unreachable" } };
  }
}

/** The public host the browser used. req.url carries the container bind address (0.0.0.0) behind Docker. */
export function requestHost(req: NextRequest): string {
  return (req.headers.get("x-forwarded-host") ?? req.headers.get("host") ?? req.nextUrl.host).split(",")[0].trim();
}

/** The public origin the browser used. */
export function origin(req: NextRequest): string {
  const proto = req.headers.get("x-forwarded-proto") ?? req.nextUrl.protocol.replace(":", "");
  return `${proto}://${requestHost(req)}`;
}

/** A 403 for a state-changing request sent from another site's page, else null. */
export function refuseCrossSite(req: NextRequest): Response | null {
  return isCrossSiteRequest(req.method, req.headers, requestHost(req)) ? Response.json({ error: "cross-site request refused" }, { status: 403 }) : null;
}

export function loginRedirect(req: NextRequest, params: Record<string, string>): NextResponse {
  const url = new URL("/login", origin(req));
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  return NextResponse.redirect(url, 303);
}

/** Redirects to `next` with the session cookies set for `user`. */
export async function signIn(req: NextRequest, user: SessionUser, next: string): Promise<NextResponse> {
  const secret = sessionSecret();
  if (!secret) return loginRedirect(req, { error: "config" });
  const secure = req.nextUrl.protocol === "https:" || req.headers.get("x-forwarded-proto") === "https";
  const res = NextResponse.redirect(new URL(next, origin(req)), 303);
  const base = { path: "/", sameSite: "lax" as const, secure, maxAge: SESSION_MAX_AGE_S };
  res.cookies.set(SESSION_COOKIE, await createSessionToken(secret, user), { ...base, httpOnly: true });
  res.cookies.set(SIGNED_IN_COOKIE, user.role, { ...base, httpOnly: false });
  return res;
}

export function toSessionUser(data: unknown): SessionUser | null {
  const u = data as Partial<SessionUser> | null;
  return u && typeof u.id === "string" && typeof u.email === "string" && (u.role === "admin" || u.role === "member") ? { id: u.id, name: String(u.name ?? ""), email: u.email, role: u.role } : null;
}
