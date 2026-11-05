import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, SESSION_MAX_AGE_S, SIGNED_IN_COOKIE, createSessionToken, safeEqual, safeNext } from "@/lib/session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** A wrong password waits before answering, which slows guessing from one client. */
const FAIL_DELAY_MS = 800;

function back(req: NextRequest, params: Record<string, string>): NextResponse {
  const url = new URL("/login", req.url);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  return NextResponse.redirect(url, 303);
}

export async function POST(req: NextRequest) {
  const form = await req.formData().catch(() => null);
  const supplied = typeof form?.get("password") === "string" ? (form!.get("password") as string) : "";
  const next = safeNext(typeof form?.get("next") === "string" ? (form!.get("next") as string) : "/");
  const password = process.env.WEB_PASSWORD;

  if (!password) return NextResponse.redirect(new URL(next, req.url), 303);
  if (!supplied || !safeEqual(supplied, password)) {
    await new Promise((r) => setTimeout(r, FAIL_DELAY_MS));
    return back(req, { error: supplied ? "wrong" : "empty", next });
  }

  const secure = req.nextUrl.protocol === "https:" || req.headers.get("x-forwarded-proto") === "https";
  const res = NextResponse.redirect(new URL(next, req.url), 303);
  const base = { path: "/", sameSite: "lax" as const, secure, maxAge: SESSION_MAX_AGE_S };
  res.cookies.set(SESSION_COOKIE, await createSessionToken(password), { ...base, httpOnly: true });
  res.cookies.set(SIGNED_IN_COOKIE, "1", { ...base, httpOnly: false });
  return res;
}
